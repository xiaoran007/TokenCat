use crate::model::*;
use crate::parsers::{parse_line, Batch, ParserState};
use crate::store::Store;
use chrono::Utc;
use sha2::{Digest, Sha256};
use std::os::unix::fs::MetadataExt;
use std::{
    collections::HashSet,
    fs::{self, File},
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    time::UNIX_EPOCH,
};

pub fn collect(store: &mut Store, config: &CoreConfig) -> CoreResult<ScanReport> {
    let mut report = ScanReport {
        checked_at_ms: Utc::now().timestamp_millis(),
        ..Default::default()
    };
    let mut sources = Vec::new();
    let codex_root = config
        .codex_root
        .clone()
        .unwrap_or_else(|| config.home.join(".codex"));
    for dir in [
        codex_root.join("sessions"),
        codex_root.join("archived_sessions"),
    ] {
        discover(&dir, Provider::Codex, &mut sources, &mut report.warnings);
    }
    let roots = if config.claude_roots.is_empty() {
        vec![
            config.home.join(".claude"),
            config.home.join(".config/claude"),
        ]
    } else {
        config.claude_roots.clone()
    };
    for root in roots {
        discover(
            &root.join("projects"),
            Provider::Claude,
            &mut sources,
            &mut report.warnings,
        );
    }
    sources.sort_by(|a, b| a.0.cmp(&b.0));
    let mut identities = HashSet::new();
    for (path, provider) in sources {
        let result = collect_source(store, &path, provider, &mut report, &mut identities);
        if let Err(error) = result {
            report.warnings.push(format!("{}: {error}", path.display()));
        }
    }
    if let Err(error) = crate::opencode::collect(store, config, &mut report) {
        report.warnings.push(format!("OpenCode: {error}"));
    }
    if let Err(error) = crate::antigravity::collect(store, config, &mut report) {
        report.warnings.push(format!("Antigravity: {error}"));
    }
    store.save_scan(&report)?;
    Ok(report)
}
fn discover(
    path: &Path,
    provider: Provider,
    sources: &mut Vec<(PathBuf, Provider)>,
    warnings: &mut Vec<String>,
) {
    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return,
        Err(e) => {
            warnings.push(format!("{}: {e}", path.display()));
            return;
        }
    };
    for entry in entries {
        let entry = match entry {
            Ok(v) => v,
            Err(e) => {
                warnings.push(format!("{}: {e}", path.display()));
                continue;
            }
        };
        let kind = match entry.file_type() {
            Ok(v) => v,
            Err(e) => {
                warnings.push(format!("{}: {e}", entry.path().display()));
                continue;
            }
        };
        // Never follow symlinks outside the explicit usage roots.
        if kind.is_dir() {
            discover(&entry.path(), provider, sources, warnings)
        } else if kind.is_file() && entry.path().extension().is_some_and(|s| s == "jsonl") {
            sources.push((entry.path(), provider));
        }
    }
}
fn modified(metadata: &fs::Metadata) -> String {
    metadata
        .modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|v| v.as_nanos().to_string())
        .unwrap_or_else(|| "unknown".into())
}
fn fingerprint(file: &mut File, offset: u64) -> CoreResult<String> {
    let n = offset.min(4096) as usize;
    let mut hash = Sha256::new();
    let mut bytes = vec![0; n];
    file.seek(SeekFrom::Start(0)).map_err(|e| e.to_string())?;
    file.read_exact(&mut bytes).map_err(|e| e.to_string())?;
    hash.update(&bytes);
    file.seek(SeekFrom::Start(offset - n as u64))
        .map_err(|e| e.to_string())?;
    file.read_exact(&mut bytes).map_err(|e| e.to_string())?;
    hash.update(&bytes);
    Ok(format!("{:x}", hash.finalize()))
}
fn collect_source(
    store: &mut Store,
    path: &Path,
    provider: Provider,
    report: &mut ScanReport,
    seen: &mut HashSet<String>,
) -> CoreResult<()> {
    let stat = fs::metadata(path).map_err(|e| e.to_string())?;
    let identity = format!("{}:{}:{}", provider.as_str(), stat.dev(), stat.ino());
    if !seen.insert(identity.clone()) {
        return Ok(());
    }
    report.files_discovered += 1;
    let previous = store.load_cursor(&identity)?;
    // Existing Codex cursors predate model-service attribution. Replay once to
    // read the allowlisted session metadata and revise stable ledger event IDs.
    let refresh_model_provider = provider == Provider::Codex
        && previous.as_ref().is_some_and(|old| {
            old.parser_state
                .get("context")
                .and_then(|context| context.get("model_provider"))
                .is_none()
        });
    let modified_ns = modified(&stat);
    let path_string = path.to_string_lossy().into_owned();
    if let Some(old) = &previous {
        if !refresh_model_provider && old.length == stat.len() && old.modified_ns == modified_ns {
            if old.path != path_string {
                let mut renamed = old.clone();
                renamed.path = path_string;
                store.commit_source(&renamed, &[], &[], &[])?;
            }
            return Ok(());
        }
    }
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let opened = file.metadata().map_err(|e| e.to_string())?;
    if opened.ino() != stat.ino() || opened.dev() != stat.dev() {
        return Err("source changed identity during scan; retry next refresh".into());
    }
    let mut state = match &previous {
        Some(old) => serde_json::from_value::<ParserState>(old.parser_state.clone())
            .map_err(|_| "unsupported persisted parser state".to_string())?,
        None => ParserState::default(),
    };
    let mut offset = previous.as_ref().map(|v| v.offset).unwrap_or(0);
    if refresh_model_provider {
        state = ParserState {
            generation: state.generation,
            ..Default::default()
        };
        offset = 0;
    }
    if let Some(old) = &previous {
        if !refresh_model_provider
            && (opened.len() < offset
                || fingerprint(&mut file, offset)? != old.head_hash
                || (opened.len() <= old.length && modified_ns != old.modified_ns))
        {
            report.warnings.push(format!(
                "{}: source rewritten or truncated; retained previous usage ledger",
                path.display()
            ));
            let generation = state.generation + 1;
            state = ParserState {
                generation,
                ..Default::default()
            };
            offset = 0;
        }
    }
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(file.take(opened.len().saturating_sub(offset)));
    let mut batch = Batch::default();
    let mut line = Vec::new();
    loop {
        line.clear();
        let read = reader
            .read_until(b'\n', &mut line)
            .map_err(|e| e.to_string())?;
        if read == 0 || line.last() != Some(&b'\n') {
            break;
        }
        let position = offset;
        offset += read as u64;
        if line.iter().all(|b| b.is_ascii_whitespace()) {
            continue;
        }
        // Error messages intentionally contain neither body text nor serde's offending values.
        let mut next_state = state.clone();
        let mut next_batch = Batch::default();
        match parse_line(provider, path, &line, &mut next_state, &mut next_batch) {
            Ok(()) => {
                state = next_state;
                batch.sessions.extend(next_batch.sessions);
                batch.events.extend(next_batch.events);
                batch.states.extend(next_batch.states);
                report.warnings.extend(
                    next_batch
                        .warnings
                        .into_iter()
                        .map(|warning| format!("{} at byte {position}: {warning}", path.display())),
                );
            }
            Err(error) => report
                .warnings
                .push(format!("{} at byte {position}: {error}", path.display())),
        }
    }
    let mut file = reader.into_inner().into_inner();
    let head_hash = fingerprint(&mut file, offset)?;
    let cursor = SourceCursor {
        identity,
        path: path_string,
        offset,
        length: opened.len(),
        modified_ns: modified(&opened),
        head_hash,
        parser_state: serde_json::to_value(state).map_err(|e| e.to_string())?,
    };
    store.commit_source(&cursor, &batch.sessions, &batch.events, &batch.states)?;
    report.files_changed += 1;
    report.events_upserted += batch.events.len();
    Ok(())
}
