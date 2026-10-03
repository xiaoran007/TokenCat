//! Antigravity's SQLite metadata ledger, read without loading prompt/response blobs.
//!
//! Field numbers were checked against the protobuf descriptors embedded in the
//! official Antigravity language_server (2026-09-30): ModelUsageStats 1=model,
//! 2=input_tokens, 3=output_tokens, 4=cache_write_tokens, 5=cache_read_tokens,
//! 6=api_provider, 9=thinking_output_tokens, 10=response_output_tokens.
//! In particular, 1 and 6 are enums, NOT token counters. Output includes thinking.
//! CortexStepGeneratorMetadata.step_indices (2) links a generation to its steps;
//! CortexStepMetadata.started_at (32) dates generations lacking ChatStartMetadata.

use crate::{model::*, store::Store};
use rusqlite::{blob::Blob, Connection, OpenFlags};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    ops::Range,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Debug)]
enum Field {
    Number(u64),
    Bytes(Range<usize>),
    Fixed,
}
type Fields = BTreeMap<u32, Vec<Field>>;

/// Read only protobuf framing and explicitly selected metadata ranges. Never
/// load the entire data/metadata column: either may contain prompt bodies.
struct MetadataReader<'a> {
    blob: Blob<'a>,
    length: usize,
}
impl<'a> MetadataReader<'a> {
    fn new(
        connection: &'a Connection,
        table: &str,
        column: &str,
        index: i64,
        length: usize,
    ) -> CoreResult<Self> {
        let blob = connection
            .blob_open("main", table, column, index, true)
            .map_err(|e| e.to_string())?;
        Ok(Self { blob, length })
    }
    fn read(&self, range: Range<usize>) -> CoreResult<Vec<u8>> {
        if range.end > self.length || range.start > range.end {
            return Err("invalid metadata range".into());
        }
        let mut bytes = vec![0; range.len()];
        self.blob
            .read_at_exact(&mut bytes, range.start)
            .map_err(|e| e.to_string())?;
        Ok(bytes)
    }
    fn varint(&self, offset: &mut usize, end: usize) -> CoreResult<u64> {
        let mut value = 0u64;
        for shift in (0..70).step_by(7) {
            if *offset >= end {
                return Err("truncated metadata varint".into());
            }
            let byte = self.read(*offset..*offset + 1)?[0];
            *offset += 1;
            if shift == 63 && byte > 1 {
                return Err("metadata varint overflow".into());
            }
            value |= u64::from(byte & 127) << shift;
            if byte < 128 {
                return Ok(value);
            }
        }
        Err("invalid metadata varint".into())
    }
    fn fields(&self, range: Range<usize>) -> CoreResult<Fields> {
        let mut offset = range.start;
        let mut fields = Fields::new();
        while offset < range.end {
            let tag = self.varint(&mut offset, range.end)?;
            let number = u32::try_from(tag >> 3).map_err(|_| "invalid protobuf tag")?;
            if number == 0 || number > 0x1fff_ffff {
                return Err("invalid protobuf tag".into());
            }
            let value = match tag & 7 {
                0 => Field::Number(self.varint(&mut offset, range.end)?),
                wire @ (1 | 5) => {
                    offset = offset
                        .checked_add(if wire == 1 { 8 } else { 4 })
                        .ok_or("metadata length overflow")?;
                    Field::Fixed
                }
                2 => {
                    let length = usize::try_from(self.varint(&mut offset, range.end)?)
                        .map_err(|_| "metadata length overflow")?;
                    let start = offset;
                    offset = offset
                        .checked_add(length)
                        .ok_or("metadata length overflow")?;
                    Field::Bytes(start..offset)
                }
                _ => return Err("unsupported metadata wire type".into()),
            };
            if offset > range.end {
                return Err("truncated metadata field".into());
            }
            fields.entry(number).or_default().push(value);
        }
        Ok(fields)
    }
    fn sub(&self, fields: &Fields, number: u32) -> CoreResult<Fields> {
        let mut output = Fields::new();
        for value in fields.get(&number).into_iter().flatten() {
            let Field::Bytes(range) = value else {
                return Err("invalid metadata message type".into());
            };
            for (key, values) in self.fields(range.clone())? {
                output.entry(key).or_default().extend(values);
            }
        }
        Ok(output)
    }
    fn text(&self, fields: &Fields, number: u32) -> CoreResult<Option<String>> {
        match fields.get(&number).and_then(|values| values.last()) {
            None => Ok(None),
            Some(Field::Bytes(range)) if range.len() <= 256 => {
                let bytes = self.read(range.clone())?;
                let text = std::str::from_utf8(&bytes)
                    .map_err(|_| "invalid metadata identifier")?
                    .trim();
                if text.is_empty() {
                    Ok(None)
                } else if text.chars().any(char::is_control) {
                    Err("invalid metadata identifier".into())
                } else {
                    Ok(Some(text.to_owned()))
                }
            }
            _ => Err("invalid metadata identifier".into()),
        }
    }
    fn timestamp(&self, fields: &Fields, number: u32) -> CoreResult<Option<i64>> {
        let stamp = self.sub(fields, number)?;
        if stamp.is_empty() {
            return Ok(None);
        }
        let seconds = number_value(&stamp, 1)?.unwrap_or(0);
        let nanos = number_value(&stamp, 2)?.unwrap_or(0);
        if seconds > 253_402_300_799 || nanos >= 1_000_000_000 {
            return Err("invalid metadata timestamp".into());
        }
        Ok(Some((seconds * 1000 + nanos / 1_000_000) as i64))
    }
    fn indices(&self, fields: &Fields) -> CoreResult<Vec<i64>> {
        let mut indices = Vec::new();
        for value in fields.get(&2).into_iter().flatten() {
            match value {
                Field::Number(value) => {
                    indices.push(i64::try_from(*value).map_err(|_| "invalid step index")?)
                }
                Field::Bytes(range) => {
                    let mut offset = range.start;
                    while offset < range.end {
                        indices.push(
                            i64::try_from(self.varint(&mut offset, range.end)?)
                                .map_err(|_| "invalid step index")?,
                        );
                    }
                }
                _ => return Err("invalid step indices".into()),
            }
        }
        Ok(indices)
    }
}
fn number_value(fields: &Fields, number: u32) -> CoreResult<Option<u64>> {
    match fields.get(&number).and_then(|values| values.last()) {
        None => Ok(None),
        Some(Field::Number(value)) => Ok(Some(*value)),
        _ => Err("invalid usage counter type".into()),
    }
}

#[derive(Clone, Debug, Serialize)]
struct Record {
    id: String,
    aliases: Vec<String>,
    session: String,
    timestamp: Option<i64>,
    revision: Option<i64>,
    model: Option<String>,
    model_provider: Option<String>,
    tokens: Tokens,
    incomplete: bool,
    #[serde(skip)]
    request_id: Option<String>,
}
fn digest(bytes: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(bytes.as_ref()))
}
fn request_id(reader: &MetadataReader<'_>, usage: &Fields) -> CoreResult<Option<String>> {
    // Response IDs exist on current Gemini metadata; other backends use message IDs.
    for field in [11, 12, 7] {
        if let Some(id) = reader.text(usage, field)? {
            return Ok(Some(id));
        }
    }
    Ok(None)
}
fn usage(fields: &Fields) -> CoreResult<Option<(Tokens, Option<String>, bool)>> {
    if fields.is_empty() {
        return Ok(None);
    }
    let input = number_value(fields, 2)?;
    let output = number_value(fields, 3)?;
    let cache_write = number_value(fields, 4)?.unwrap_or(0);
    let cache_read = number_value(fields, 5)?.unwrap_or(0);
    let thinking = number_value(fields, 9)?;
    let response = number_value(fields, 10)?;
    if input.is_none()
        && output.is_none()
        && cache_write == 0
        && cache_read == 0
        && thinking.is_none()
        && response.is_none()
    {
        return Ok(None);
    }
    // Proto3 omits zero-valued counters. Once a usage message has counters, their
    // missing numeric siblings are zero; absence of the usage message is unknown.
    let input = input.unwrap_or(0);
    let output = match output {
        Some(value) => value,
        None if thinking.is_some() || response.is_some() => thinking
            .unwrap_or(0)
            .checked_add(response.unwrap_or(0))
            .ok_or("usage overflow")?,
        None => 0,
    };
    let incomplete = thinking.is_some_and(|v| v > output)
        || (thinking.is_some() || response.is_some())
            && thinking.unwrap_or(0).checked_add(response.unwrap_or(0)) != Some(output);
    let total = input
        .checked_add(cache_read)
        .and_then(|v| v.checked_add(cache_write))
        .and_then(|v| v.checked_add(output))
        .ok_or("usage overflow")?;
    let provider = match number_value(fields, 6)? {
        Some(24) => Some("gemini".into()),
        Some(3 | 26 | 31) => Some("vertex_ai".into()),
        _ => None,
    };
    // Response headers and service/account metadata are deliberately not read.
    Ok(Some((
        Tokens {
            input_uncached: Some(input),
            cache_read: Some(cache_read),
            cache_write: Some(cache_write),
            cache_write_5m: if cache_write == 0 { Some(0) } else { None },
            cache_write_1h: if cache_write == 0 { Some(0) } else { None },
            output: Some(output),
            reasoning: if incomplete { None } else { thinking },
            total: Some(total),
        },
        provider,
        incomplete,
    )))
}
fn stable_id(session: &str, request: &Option<String>, position: &str) -> String {
    digest(match request {
        Some(request) => format!("antigravity:request:{request}"),
        None => format!("antigravity:session:{session}:{position}"),
    })
}
fn rows(connection: &Connection, table: &str, column: &str) -> CoreResult<Vec<(i64, usize)>> {
    let mut statement = connection
        .prepare(&format!(
            "SELECT idx, length({column}) FROM {table} WHERE typeof({column})='blob' ORDER BY idx"
        ))
        .map_err(|e| e.to_string())?;
    let rows = statement
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
        .map_err(|e| e.to_string())?;
    rows.collect::<Result<_, _>>().map_err(|e| e.to_string())
}
fn has_table(connection: &Connection, table: &str) -> CoreResult<bool> {
    connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1)",
            [table],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
}
fn read_step(
    connection: &Connection,
    session: &str,
    index: i64,
    length: usize,
) -> CoreResult<Option<Record>> {
    let reader = MetadataReader::new(connection, "steps", "metadata", index, length)?;
    let fields = reader.fields(0..length)?;
    let counters = reader.sub(&fields, 9)?;
    let Some((tokens, provider, incomplete)) = usage(&counters)? else {
        return Ok(None);
    };
    let request = request_id(&reader, &counters)?;
    let timestamp = reader
        .timestamp(&fields, 32)?
        .or(reader.timestamp(&fields, 1)?);
    let revision = [
        reader.timestamp(&fields, 8)?,
        reader.timestamp(&fields, 7)?,
        reader.timestamp(&fields, 22)?,
        timestamp,
    ]
    .into_iter()
    .flatten()
    .max();
    let model_info = reader.sub(&fields, 24)?;
    let id = stable_id(session, &request, &format!("step:{index}"));
    Ok(Some(Record {
        aliases: vec![
            id.clone(),
            stable_id(session, &None, &format!("step:{index}")),
        ],
        id,
        session: session.into(),
        timestamp,
        revision,
        model: reader.text(&model_info, 8)?,
        model_provider: provider,
        tokens,
        incomplete,
        request_id: request,
    }))
}
fn read_generation(
    connection: &Connection,
    session: &str,
    index: i64,
    length: usize,
    steps: &BTreeMap<i64, Record>,
) -> CoreResult<Option<(Record, Vec<i64>)>> {
    let reader = MetadataReader::new(connection, "gen_metadata", "data", index, length)?;
    let fields = reader.fields(0..length)?;
    let chat = reader.sub(&fields, 1)?;
    let counters = reader.sub(&chat, 4)?;
    let Some((mut tokens, mut provider, mut incomplete)) = usage(&counters)? else {
        return Ok(None);
    };
    let request = request_id(&reader, &counters)?;
    let indices = reader.indices(&fields)?;
    let linked = indices
        .iter()
        .filter_map(|idx| steps.get(idx).map(|step| (*idx, step)))
        .filter(|(_, step)| match (&request, &step.request_id) {
            (Some(left), Some(right)) => left == right,
            // Explicit step indices still identify this generation before a
            // streaming usage snapshot receives its response/message ID.
            _ => true,
        })
        .collect::<Vec<_>>();
    let start = reader.timestamp(&reader.sub(&chat, 9)?, 4)?;
    let timestamp = start.or_else(|| linked.iter().filter_map(|(_, step)| step.timestamp).min());
    let revision = linked
        .iter()
        .filter_map(|(_, step)| step.revision)
        .chain(start)
        .max();
    let request = request.or_else(|| linked.iter().find_map(|(_, step)| step.request_id.clone()));
    for (_, step) in &linked {
        if step.tokens.total > tokens.total {
            tokens = step.tokens.clone();
            incomplete = step.incomplete;
        }
        if provider.is_none() {
            provider = step.model_provider.clone();
        }
    }
    let position = linked
        .first()
        .map(|(idx, _)| format!("step:{idx}"))
        .unwrap_or_else(|| format!("generation:{index}"));
    let model = reader
        .text(&chat, 19)?
        .or(reader.text(&chat, 22)?)
        .or_else(|| linked.iter().find_map(|(_, step)| step.model.clone()));
    let id = stable_id(session, &request, &position);
    let mut aliases = vec![
        id.clone(),
        stable_id(session, &None, &format!("generation:{index}")),
    ];
    // Keep positional identities even before their step rows have been flushed.
    aliases.extend(
        indices
            .iter()
            .filter(|idx| {
                !steps.contains_key(idx) || linked.iter().any(|(linked_idx, _)| linked_idx == *idx)
            })
            .map(|idx| stable_id(session, &None, &format!("step:{idx}"))),
    );
    aliases.extend(linked.iter().flat_map(|(_, step)| step.aliases.clone()));
    Ok(Some((
        Record {
            id,
            aliases,
            session: session.into(),
            timestamp,
            revision,
            model,
            model_provider: provider,
            tokens,
            incomplete,
            request_id: request,
        },
        linked.into_iter().map(|(idx, _)| idx).collect(),
    )))
}
#[derive(Clone, Serialize)]
struct DatabaseUsage {
    records: Vec<Record>,
    session: SessionMetadata,
}
fn local_file_path(uri: &str) -> Option<String> {
    let encoded = uri.strip_prefix("file://")?;
    let encoded = encoded
        .strip_prefix("localhost/")
        .map(|path| format!("/{path}"))
        .unwrap_or_else(|| encoded.to_string());
    if !encoded.starts_with('/') {
        return None;
    }
    let bytes = encoded.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let high = char::from(*bytes.get(index + 1)?).to_digit(16)?;
            let low = char::from(*bytes.get(index + 2)?).to_digit(16)?;
            decoded.push((high * 16 + low) as u8);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    let path = String::from_utf8(decoded).ok()?;
    (!path.chars().any(char::is_control)).then_some(path)
}
fn read_session(connection: &Connection, session: &str) -> CoreResult<SessionMetadata> {
    let mut metadata = SessionMetadata {
        id: session.into(),
        provider: Provider::Antigravity,
        parent_id: None,
        project_path: None,
        title: None,
    };
    if !has_table(connection, "trajectory_metadata_blob")? {
        return Ok(metadata);
    }
    use rusqlite::OptionalExtension;
    let row: Option<(i64, usize)> = connection.query_row(
        "SELECT rowid,length(data) FROM trajectory_metadata_blob WHERE id='main' AND typeof(data)='blob'",
        [], |row| Ok((row.get(0)?, row.get(1)?))
    ).optional().map_err(|e| e.to_string())?;
    let Some((index, length)) = row else {
        return Ok(metadata);
    };
    let reader = MetadataReader::new(connection, "trajectory_metadata_blob", "data", index, length)?;
    let fields = reader.fields(0..length)?;
    metadata.parent_id = reader.text(&fields, 5)?.filter(|parent| parent != session);
    let mut workspaces = BTreeSet::new();
    let mut has_other_workspace = false;
    for value in fields.get(&7).into_iter().flatten() {
        let Field::Bytes(range) = value else {
            return Err("invalid workspace metadata".into());
        };
        if range.len() > 4096 {
            return Err("invalid workspace metadata".into());
        }
        let bytes = reader.read(range.clone())?;
        let uri = std::str::from_utf8(&bytes).map_err(|_| "invalid workspace metadata")?;
        if let Some(path) = local_file_path(uri) {
            workspaces.insert(path);
        } else {
            has_other_workspace = true;
        }
    }
    // A multi-workspace conversation cannot be assigned to one project honestly.
    if !has_other_workspace && workspaces.len() == 1 {
        metadata.project_path = workspaces.into_iter().next();
    }
    Ok(metadata)
}
struct Snapshot {
    version: i64,
    usage: DatabaseUsage,
    warnings: Vec<String>,
}

struct CachedDatabase {
    identity: (u64, u64),
    connection: Connection,
    snapshot: Option<Snapshot>,
    #[cfg(test)]
    parses: usize,
}

/// Owned by one engine; connections never outlive its configuration.
#[derive(Default)]
pub struct Cache {
    databases: BTreeMap<PathBuf, CachedDatabase>,
}

impl Cache {
    pub fn collect(
        &mut self,
        store: &mut Store,
        config: &CoreConfig,
        report: &mut ScanReport,
    ) -> CoreResult<()> {
        collect_cached(self, store, config, report)
    }

    fn read(&mut self, path: &Path, report: &mut ScanReport) -> CoreResult<DatabaseUsage> {
        let result = self.read_cached(path, report);
        if result.is_err() {
            // Failed reads must not leave a snapshot or a bad connection reusable.
            self.databases.remove(path);
        }
        result
    }

    fn read_cached(&mut self, path: &Path, report: &mut ScanReport) -> CoreResult<DatabaseUsage> {
        let metadata = fs::metadata(path).map_err(|e| e.to_string())?;
        let identity = (metadata.dev(), metadata.ino());
        if self.databases.get(path).is_none_or(|old| old.identity != identity) {
            // Close the old handle before opening an atomically replaced file.
            self.databases.remove(path);
            let connection = Connection::open_with_flags(
                path,
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            ).map_err(|e| e.to_string())?;
            connection.busy_timeout(Duration::from_millis(250)).map_err(|e| e.to_string())?;
            connection.execute_batch("PRAGMA cache_size=-256").map_err(|e| e.to_string())?;
            self.databases.insert(path.to_owned(), CachedDatabase {
                identity, connection, snapshot: None,
                #[cfg(test)]
                parses: 0,
            });
        }
        let database = self.databases.get_mut(path).expect("opened source database");
        let before = data_version(&database.connection)?;
        if let Some(snapshot) = &database.snapshot {
            if snapshot.version == before {
                report.warnings.extend(snapshot.warnings.clone());
                return Ok(snapshot.usage.clone());
            }
        }
        database.snapshot = None;
        #[cfg(test)]
        { database.parses += 1; }
        let mut local = ScanReport::default();
        let usage = read_database(&database.connection, path, &mut local)?;
        // A concurrent commit may precede or follow the transaction's snapshot.
        // Cache only when no outside commit occurred across that whole interval.
        if data_version(&database.connection)? == before {
            database.snapshot = Some(Snapshot {
                version: before, usage: usage.clone(), warnings: local.warnings.clone(),
            });
        }
        report.warnings.extend(local.warnings);
        Ok(usage)
    }
}

fn data_version(connection: &Connection) -> CoreResult<i64> {
    connection.query_row("PRAGMA data_version", [], |row| row.get(0))
        .map_err(|e| e.to_string())
}

fn read_database(connection: &Connection, path: &Path, report: &mut ScanReport) -> CoreResult<DatabaseUsage> {
    // One consistent WAL snapshot, with no writes or journal mode changes.
    let transaction = connection
        .unchecked_transaction()
        .map_err(|e| e.to_string())?;
    let session = path
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or("invalid conversation identifier")?;
    let metadata = read_session(&transaction, session)?;
    if !has_table(&transaction, "gen_metadata")? {
        return Ok(DatabaseUsage {
            records: Vec::new(),
            session: metadata,
        });
    }
    let mut steps = BTreeMap::new();
    if has_table(&transaction, "steps")? {
        for (index, length) in rows(&transaction, "steps", "metadata")? {
            match read_step(&transaction, session, index, length) {
                Ok(Some(step)) => {
                    steps.insert(index, step);
                }
                Ok(None) => (),
                Err(_) => report
                    .warnings
                    .push("Antigravity: one step has unsupported usage metadata".into()),
            }
        }
    }
    let mut result = Vec::new();
    let mut consumed = BTreeSet::new();
    for (index, length) in rows(&transaction, "gen_metadata", "data")? {
        match read_generation(&transaction, session, index, length, &steps) {
            Ok(Some((record, linked))) => {
                result.push(record);
                consumed.extend(linked);
            }
            Ok(None) => (),
            Err(_) => report
                .warnings
                .push("Antigravity: one generation has unsupported usage metadata".into()),
        }
    }
    // Interrupted requests can have durable step usage before gen_metadata is
    // flushed. Retain these requests too, deduplicating by their stable IDs.
    result.extend(
        steps
            .into_iter()
            .filter(|(idx, _)| !consumed.contains(idx))
            .map(|(_, record)| record),
    );
    Ok(DatabaseUsage {
        records: result,
        session: metadata,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Source {
        root: PathBuf,
        path: PathBuf,
        writer: Option<Connection>,
    }

    impl Source {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("tokencat-cache-{}-{}",
                std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            fs::create_dir_all(root.join("conversations")).unwrap();
            let path = root.join("conversations/session.db");
            let writer = Connection::open(&path).unwrap();
            writer.execute_batch("PRAGMA journal_mode=WAL;
                CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY,data BLOB);
                INSERT INTO gen_metadata VALUES(0,x'');").unwrap();
            Self { root, path, writer: Some(writer) }
        }

        fn writer(&self) -> &Connection { self.writer.as_ref().unwrap() }

        fn config(&self) -> CoreConfig {
            CoreConfig {
                home: self.root.clone(), database_path: self.root.join("usage.db"),
                codex_root: None, claude_roots: vec![], opencode_root: None,
                antigravity_roots: vec![self.root.clone()], pricing_path: None,
            }
        }
    }

    impl Drop for Source {
        fn drop(&mut self) { fs::remove_dir_all(&self.root).unwrap(); }
    }

    #[test]
    fn unchanged_cache_reuses_metadata_and_replays_warnings_after_wal_changes() {
        let source = Source::new();
        let mut cache = Cache::default();
        let mut report = ScanReport::default();
        cache.read(&source.path, &mut report).unwrap();
        cache.read(&source.path, &mut report).unwrap();
        assert_eq!(cache.databases[&source.path].parses, 1);
        let connection = &cache.databases[&source.path].connection;
        assert_eq!(connection.query_row("PRAGMA cache_size", [], |row| row.get::<_, i64>(0)).unwrap(), -256);
        assert!(connection.execute("INSERT INTO gen_metadata VALUES(1,x'')", []).is_err());
        source.writer().execute_batch("UPDATE gen_metadata SET data=x'ff' WHERE idx=0").unwrap();
        cache.read(&source.path, &mut report).unwrap();
        assert_eq!(cache.databases[&source.path].parses, 2);
        assert_eq!(report.warnings.len(), 1);
        report.warnings.clear();
        cache.read(&source.path, &mut report).unwrap();
        assert_eq!(cache.databases[&source.path].parses, 2);
        assert_eq!(report.warnings.len(), 1);
        source.writer().execute_batch("UPDATE gen_metadata SET data=x'' WHERE idx=0;
            PRAGMA wal_checkpoint(TRUNCATE)").unwrap();
        report.warnings.clear();
        cache.read(&source.path, &mut report).unwrap();
        assert!(report.warnings.is_empty());
    }

    #[test]
    fn failed_database_read_discards_cache_and_can_recover() {
        let source = Source::new();
        let mut cache = Cache::default();
        let mut report = ScanReport::default();
        cache.read(&source.path, &mut report).unwrap();
        source.writer().execute_batch("ALTER TABLE gen_metadata RENAME COLUMN data TO payload").unwrap();
        assert!(cache.read(&source.path, &mut report).is_err());
        assert!(cache.databases.is_empty());
        source.writer().execute_batch("ALTER TABLE gen_metadata RENAME COLUMN payload TO data").unwrap();
        cache.read(&source.path, &mut report).unwrap();
        assert_eq!(cache.databases.len(), 1);
    }

    #[test]
    fn replacement_reopens_connection_and_removed_paths_are_pruned() {
        let mut source = Source::new();
        let mut cache = Cache::default();
        let mut report = ScanReport::default();
        cache.read(&source.path, &mut report).unwrap();
        let identity = cache.databases[&source.path].identity;
        let replacement = source.root.join("replacement.db");
        let writer = Connection::open(&replacement).unwrap();
        writer.execute_batch("CREATE TABLE gen_metadata(idx INTEGER PRIMARY KEY,data BLOB);
            INSERT INTO gen_metadata VALUES(0,x'ff')").unwrap();
        drop(writer);
        // Finish the old SQLite file set before atomically replacing its main file.
        source.writer().execute_batch("PRAGMA wal_checkpoint(TRUNCATE)").unwrap();
        source.writer.take().unwrap().close().unwrap();
        fs::rename(&replacement, &source.path).unwrap();
        cache.read(&source.path, &mut report).unwrap();
        assert_ne!(cache.databases[&source.path].identity, identity);
        assert_eq!(report.warnings.len(), 1);
        fs::remove_file(&source.path).unwrap();
        let config = source.config();
        let mut store = Store::open(&config.database_path).unwrap();
        cache.collect(&mut store, &config, &mut ScanReport::default()).unwrap();
        assert!(cache.databases.is_empty());
    }

    #[test]
    fn engine_owns_cache_and_new_configuration_starts_empty() {
        let source = Source::new();
        let mut engine = crate::Engine::open(source.config()).unwrap();
        engine.scan().unwrap();
        engine.scan().unwrap();
        assert_eq!(engine.antigravity.databases[&source.path].parses, 1);
        drop(engine);
        let mut reopened = crate::Engine::open(source.config()).unwrap();
        assert!(reopened.antigravity.databases.is_empty());
        reopened.scan().unwrap();
        assert_eq!(reopened.antigravity.databases[&source.path].parses, 1);
        drop(reopened);
        let other = Source::new();
        let mut engine = crate::Engine::open(other.config()).unwrap();
        assert!(engine.antigravity.databases.is_empty());
        engine.scan().unwrap();
        assert!(engine.antigravity.databases.contains_key(&other.path));
        assert!(!engine.antigravity.databases.contains_key(&source.path));
    }

    #[test]
    fn blob_reader_skips_large_body_and_validates_ranges() {
        let connection = Connection::open_in_memory().unwrap();
        connection.execute_batch("CREATE TABLE metadata(data BLOB)").unwrap();
        // Field 1 is a 256 KiB body, followed by field 2 = 42.
        let mut data = vec![0x0a, 0x80, 0x80, 0x10];
        data.extend(vec![0xff; 256 * 1024]);
        data.extend([0x10, 42]);
        connection.execute("INSERT INTO metadata(data) VALUES(?1)", [&data]).unwrap();
        let reader = MetadataReader::new(&connection, "metadata", "data", 1, data.len()).unwrap();
        let fields = reader.fields(0..data.len()).unwrap();
        assert!(matches!(fields[&1][0], Field::Bytes(_)));
        assert!(matches!(fields[&2][0], Field::Number(42)));
        assert!(reader.read(data.len()..data.len() + 1).is_err());
        assert!(reader.read(2..1).is_err());
    }
}
fn discover(roots: &[PathBuf], report: &mut ScanReport) -> Vec<PathBuf> {
    let mut paths = BTreeSet::new();
    for root in roots {
        match fs::read_dir(root.join("conversations")) {
            Ok(entries) => {
                for entry in entries {
                    match entry {
                        Ok(entry) => match entry.file_type() {
                            Ok(kind)
                                if kind.is_file()
                                    && entry.path().extension().is_some_and(|ext| ext == "db") =>
                            {
                                paths.insert(entry.path());
                            }
                            Ok(_) => (),
                            Err(_) => report
                                .warnings
                                .push("Antigravity: conversation metadata is unavailable".into()),
                        },
                        Err(_) => report
                            .warnings
                            .push("Antigravity: conversation metadata is unavailable".into()),
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => report
                .warnings
                .push("Antigravity: conversation directory is unavailable".into()),
        }
    }
    paths.into_iter().collect()
}
fn preference(record: &Record) -> (Option<i64>, u64, bool, bool) {
    (
        record.revision,
        record.tokens.total.unwrap_or(0),
        record.model.is_some(),
        !record.incomplete,
    )
}

const IDENTITIES: &str = "antigravity:event-identities";
fn alias_root(aliases: &BTreeMap<String, String>, alias: &str) -> String {
    let mut root = alias;
    while let Some(parent) = aliases.get(root) {
        if parent == root {
            break;
        }
        root = parent;
    }
    root.to_owned()
}
fn join_aliases(aliases: &mut BTreeMap<String, String>, left: &str, right: &str) {
    let left = alias_root(aliases, left);
    let right = alias_root(aliases, right);
    if left < right {
        aliases.insert(right, left);
    } else if right < left {
        aliases.insert(left, right);
    }
}

/// Preserve the first ledger identity when later metadata adds a response ID or
/// a step record. Persist hashed aliases across scans and source moves/copies.
fn reconcile_identities(
    store: &Store,
    records: &mut [Record],
) -> CoreResult<BTreeMap<String, String>> {
    let old = store.load_cursor(IDENTITIES)?;
    let previous: BTreeMap<String, String> = old
        .as_ref()
        .map(|cursor| {
            serde_json::from_value(cursor.parser_state.clone())
                .map_err(|_| "invalid Antigravity identity state".to_string())
        })
        .transpose()?
        .unwrap_or_default();
    let mut groups = BTreeMap::new();
    for (alias, id) in &previous {
        join_aliases(&mut groups, alias, id);
    }
    for record in records.iter() {
        for alias in &record.aliases {
            join_aliases(&mut groups, &record.id, alias);
        }
    }
    let mut preferred = BTreeMap::<String, String>::new();
    for id in previous.values() {
        preferred
            .entry(alias_root(&groups, id))
            .and_modify(|known| {
                if id < known {
                    *known = id.clone();
                }
            })
            .or_insert_with(|| id.clone());
    }
    let resolve = |alias: &str| {
        let root = alias_root(&groups, alias);
        preferred.get(&root).cloned().unwrap_or(root)
    };
    let mut retired = BTreeMap::<String, BTreeSet<String>>::new();
    for id in previous.values() {
        let canonical = resolve(id);
        if canonical != *id {
            retired.entry(canonical).or_default().insert(id.clone());
        }
    }
    // A later response ID can prove two previously unidentified copies were the
    // same request. Merge their ledger rows before replacing the identity map;
    // interrupted scans will rediscover and retry this idempotent merge.
    for (canonical, ids) in retired {
        store.merge_event_ids(
            Provider::Antigravity,
            &canonical,
            &ids.into_iter().collect::<Vec<_>>(),
        )?;
    }
    let mut resolved = BTreeMap::new();
    for alias in previous
        .keys()
        .chain(previous.values())
        .chain(records.iter().flat_map(|record| record.aliases.iter()))
    {
        resolved.insert(alias.clone(), resolve(alias));
    }
    for record in records.iter_mut() {
        record.id = resolve(&record.id);
    }
    if previous != resolved {
        let fingerprint = digest(serde_json::to_vec(&resolved).map_err(|e| e.to_string())?);
        let cursor = SourceCursor {
            identity: IDENTITIES.into(),
            path: IDENTITIES.into(),
            offset: 0,
            length: resolved.len() as u64,
            modified_ns: String::new(),
            head_hash: fingerprint,
            parser_state: serde_json::to_value(&resolved).map_err(|e| e.to_string())?,
        };
        // Saving identity mappings before usage is safe if interrupted: the next
        // scan reuses these IDs. Saving them after usage could leave orphan IDs.
        store.commit_source(&cursor, &[], &[], &[])?;
    }
    Ok(resolved)
}

pub fn collect(store: &mut Store, config: &CoreConfig, report: &mut ScanReport) -> CoreResult<()> {
    Cache::default().collect(store, config, report)
}

fn collect_cached(cache: &mut Cache, store: &mut Store, config: &CoreConfig, report: &mut ScanReport) -> CoreResult<()> {
    let roots = if config.antigravity_roots.is_empty() {
        vec![
            config.home.join(".gemini/antigravity"),
            config.home.join(".gemini/antigravity-cli"),
        ]
    } else {
        config.antigravity_roots.clone()
    };
    let paths = discover(&roots, report);
    cache.databases.retain(|path, _| paths.binary_search(path).is_ok());
    let mut pending = Vec::new();
    let mut session_metadata = BTreeMap::<String, SessionMetadata>::new();
    let mut cursors = Vec::new();
    for path in paths {
        report.files_discovered += 1;
        let data = match cache.read(&path, report) {
            Ok(data) => data,
            Err(_) => {
                report
                    .warnings
                    .push("Antigravity: a conversation database could not be read".into());
                continue;
            }
        };
        let fingerprint = digest(serde_json::to_vec(&data).map_err(|e| e.to_string())?);
        let identity = format!("antigravity:{}", digest(path.to_string_lossy().as_bytes()));
        let previous = store.load_cursor(&identity)?;
        let ids = data
            .records
            .iter()
            .map(|record| record.id.clone())
            .collect::<BTreeSet<_>>();
        let session = data.session;
        session_metadata
            .entry(session.id.clone())
            .and_modify(|existing| {
                if session.parent_id.is_some() {
                    existing.parent_id = session.parent_id.clone();
                }
                if session.project_path.is_some() {
                    existing.project_path = session.project_path.clone();
                }
            })
            .or_insert(session);
        pending.extend(data.records);
        if previous
            .as_ref()
            .is_some_and(|old| old.head_hash == fingerprint)
        {
            continue;
        }
        cursors.push((
            SourceCursor {
                identity,
                path: path.to_string_lossy().into_owned(),
                offset: 0,
                length: ids.len() as u64,
                modified_ns: String::new(),
                head_hash: fingerprint,
                parser_state: json!({"schema":1}),
            },
            ids,
        ));
    }
    let identities = reconcile_identities(store, &mut pending)?;
    let mut records = BTreeMap::<String, Record>::new();
    for mut record in pending {
        match records.get_mut(&record.id) {
            Some(existing) => {
                if preference(&record) > preference(existing) {
                    record.model = record.model.or(existing.model.clone());
                    record.model_provider =
                        record.model_provider.or(existing.model_provider.clone());
                    *existing = record;
                } else {
                    existing.model = existing.model.clone().or(record.model);
                    existing.model_provider =
                        existing.model_provider.clone().or(record.model_provider);
                }
            }
            None => {
                records.insert(record.id.clone(), record);
            }
        }
    }
    for record in records.values().filter(|record| record.timestamp.is_none()) {
        report.undated_events += 1;
        report.undated_tokens = report
            .undated_tokens
            .saturating_add(record.tokens.total.unwrap_or(0));
    }
    let mut upserted = BTreeSet::new();
    for (cursor, ids) in cursors {
        let ids = ids
            .into_iter()
            .filter_map(|id| identities.get(&id).cloned())
            .collect::<BTreeSet<_>>();
        let records = ids
            .iter()
            .filter_map(|id| records.get(id))
            .filter(|record| record.timestamp.is_some())
            .collect::<Vec<_>>();
        let events = records
            .iter()
            .map(|record| UsageEvent {
                id: record.id.clone(),
                provider: Provider::Antigravity,
                session_id: record.session.clone(),
                timestamp_ms: record.timestamp.unwrap(),
                revision_ms: record.revision,
                model: record.model.clone(),
                model_provider: record.model_provider.clone(),
                attribution: if record.model.is_some() {
                    "exact"
                } else {
                    "unattributed"
                }
                .into(),
                tokens: record.tokens.clone(),
                incomplete: record.incomplete,
            })
            .collect::<Vec<_>>();
        let sessions = records
            .iter()
            .map(|record| record.session.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .filter_map(|id| session_metadata.get(&id).cloned())
            .collect::<Vec<_>>();
        store.commit_source(&cursor, &sessions, &events, &[])?;
        report.files_changed += 1;
        upserted.extend(events.into_iter().map(|event| event.id));
    }
    report.events_upserted += upserted.len();
    Ok(())
}
