//! Read-only OpenCode SQLite usage projections; SQL never returns message bodies.
//!
//! OpenCode's `getUsage` stores uncached input and separates reasoning from output.
//! The legacy processor overwrites message.tokens at every step, while each
//! step-finish part records one request. Read those parts once, not both totals.
//! Sources: anomalyco/opencode packages/opencode/src/session/{session,processor}.ts
//! and packages/core/src/session/{sql,message-updater}.ts (2026-10-02).
use crate::{model::*, store::Store};
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    path::PathBuf,
    time::Duration,
};

#[derive(Deserialize)]
struct Usage {
    input: Option<u64>,
    output: Option<u64>,
    reasoning: Option<u64>,
    read: Option<u64>,
    write: Option<u64>,
    total: Option<u64>,
}

impl Usage {
    fn tokens(&self) -> CoreResult<Tokens> {
        fn sum(values: &[Option<u64>]) -> CoreResult<Option<u64>> {
            values.iter().try_fold(Some(0_u64), |sum, value| {
                sum.zip(*value)
                    .map(|(sum, value)| sum.checked_add(value).ok_or("token count overflow".into()))
                    .transpose()
            })
        }
        let output = if self.output.is_some() || self.reasoning.is_some() {
            Some(self.output.unwrap_or(0).checked_add(self.reasoning.unwrap_or(0)).ok_or("token count overflow")?)
        } else { None };
        // Retain observed categories and any larger reported total. Missing
        // categories are not fabricated to make the breakdown match the total.
        let observed = [
            self.input,
            self.output,
            self.reasoning,
            self.read,
            self.write,
        ]
        .into_iter()
        .flatten()
        .try_fold(0_u64, |sum, value| {
            sum.checked_add(value).ok_or("token count overflow")
        })?;
        Ok(Tokens {
            input_uncached: self.input,
            cache_read: self.read,
            cache_write: self.write,
            output,
            reasoning: self.reasoning,
            total: Some(self.total.unwrap_or(observed)
                .max(sum(&[self.input, self.read, self.write, output])?.unwrap_or(observed))),
            ..Tokens::default()
        })
    }

    fn nonzero(&self) -> bool {
        [
            self.input,
            self.output,
            self.reasoning,
            self.read,
            self.write,
            self.total,
        ]
        .iter()
        .any(|value| value.is_some_and(|value| value > 0))
    }
}

struct Session {
    metadata: SessionMetadata,
    created_ms: i64,
}

struct Message {
    id: String,
    session_id: String,
    created_ms: i64,
    updated_ms: i64,
    model: Option<String>,
    model_provider: Option<String>,
    usage: String,
}

struct Step {
    id: String,
    created_ms: i64,
    updated_ms: i64,
    usage: String,
}

fn root(config: &CoreConfig) -> PathBuf {
    if let Some(root) = &config.opencode_root {
        return root.clone();
    }
    // An explicitly supplied alternate home must never scan the real user's data.
    if std::env::var_os("HOME").is_some_and(|home| PathBuf::from(home) == config.home) {
        if let Some(data_home) = std::env::var_os("XDG_DATA_HOME") {
            let path = PathBuf::from(data_home);
            if path.is_absolute() {
                return path.join("opencode");
            }
        }
    }
    config.home.join(".local/share/opencode")
}

fn has_table(connection: &Connection, table: &str) -> CoreResult<bool> {
    connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?1)",
            [table],
            |row| row.get(0),
        )
        .map_err(|error| error.to_string())
}

// The table names/JSON paths here are internal constants, never external input.
fn usage_sql(data: &str) -> String {
    format!(
        "json_object('input',json_extract({data},'$.tokens.input'),
          'output',json_extract({data},'$.tokens.output'),
          'reasoning',json_extract({data},'$.tokens.reasoning'),
          'read',json_extract({data},'$.tokens.cache.read'),
          'write',json_extract({data},'$.tokens.cache.write'),
          'total',json_extract({data},'$.tokens.total'))"
    )
}

fn messages(connection: &Connection, modern: bool) -> CoreResult<Vec<Message>> {
    let (table, role, model, provider) = if modern {
        (
            "session_message",
            "m.type='assistant'",
            "$.model.id",
            "$.model.providerID",
        )
    } else {
        (
            "message",
            "json_extract(m.data,'$.role')='assistant'",
            "$.modelID",
            "$.providerID",
        )
    };
    if !has_table(connection, table)? {
        return Ok(Vec::new());
    }
    let sql = format!(
        "SELECT m.id,m.session_id,m.time_created,m.time_updated,
                json_extract(m.data,'{model}'),json_extract(m.data,'{provider}'),{}
         FROM {table} m WHERE CASE WHEN json_valid(m.data) THEN {role} ELSE 0 END
         ORDER BY m.time_created,m.id",
        usage_sql("m.data")
    );
    let mut statement = connection
        .prepare(&sql)
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map([], |row| {
            Ok(Message {
                id: row.get(0)?,
                session_id: row.get(1)?,
                created_ms: row.get(2)?,
                updated_ms: row.get(3)?,
                model: row.get(4)?,
                model_provider: row.get(5)?,
                usage: row.get(6)?,
            })
        })
        .map_err(|error| error.to_string())?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())
}

fn steps(connection: &Connection) -> CoreResult<HashMap<String, Vec<Step>>> {
    let mut result: HashMap<String, Vec<Step>> = HashMap::new();
    if !has_table(connection, "part")? {
        return Ok(result);
    }
    let sql = format!(
        "SELECT p.message_id,p.id,p.time_created,p.time_updated,{} FROM part p
         WHERE CASE WHEN json_valid(p.data) THEN json_extract(p.data,'$.type')='step-finish' ELSE 0 END
         ORDER BY p.time_created,p.id", usage_sql("p.data")
    );
    let mut statement = connection
        .prepare(&sql)
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                Step {
                    id: row.get(1)?,
                    created_ms: row.get(2)?,
                    updated_ms: row.get(3)?,
                    usage: row.get(4)?,
                },
            ))
        })
        .map_err(|error| error.to_string())?;
    for row in rows {
        let (message_id, step) = row.map_err(|error| error.to_string())?;
        result.entry(message_id).or_default().push(step);
    }
    Ok(result)
}

fn event(
    message: &Message,
    id: String,
    timestamp_ms: i64,
    revision_ms: i64,
    raw: &str,
) -> CoreResult<Option<UsageEvent>> {
    // Error text intentionally omits JSON values, which can contain arbitrary source data.
    let usage: Usage = serde_json::from_str(raw).map_err(|_| "invalid token counts")?;
    if !usage.nonzero() {
        return Ok(None);
    }
    let tokens = usage.tokens()?;
    let incomplete = [
        usage.input, usage.read, usage.write, usage.output, usage.reasoning,
    ]
    .iter()
    .any(Option::is_none)
        || usage
            .total
            .is_some_and(|reported| reported != tokens.known_total());
    Ok(Some(UsageEvent {
        uncertain_time: (timestamp_ms <= 0).then_some(TimeBounds::default()),
        id,
        provider: Provider::OpenCode,
        session_id: message.session_id.clone(),
        timestamp_ms,
        revision_ms: Some(revision_ms.max(timestamp_ms)),
        model: message
            .model
            .clone()
            .filter(|value| !value.trim().is_empty()),
        model_provider: message
            .model_provider
            .clone()
            .filter(|value| !value.trim().is_empty()),
        attribution: if message.model.is_some() {
            "explicit"
        } else {
            "unattributed"
        }
        .into(),
        tokens,
        incomplete,
    }))
}

pub fn collect(store: &mut Store, config: &CoreConfig, report: &mut ScanReport) -> CoreResult<()> {
    let path = root(config).join("opencode.db");
    if !path.is_file() {
        return Ok(());
    }
    report.files_discovered += 1;
    let mut connection = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|error| error.to_string())?;
    connection
        .busy_timeout(Duration::from_secs(2))
        .map_err(|error| error.to_string())?;
    connection
        .pragma_update(None, "query_only", true)
        .map_err(|error| error.to_string())?;
    // A normal read transaction includes the current WAL; immutable=1 would lose it.
    let transaction = connection
        .transaction()
        .map_err(|error| error.to_string())?;
    let mut sessions = BTreeMap::new();
    {
        let mut statement = transaction
            .prepare("SELECT id,parent_id,directory,time_created FROM session ORDER BY id")
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| {
                Ok(Session {
                    metadata: SessionMetadata {
                        id: row.get(0)?,
                        provider: Provider::OpenCode,
                        parent_id: row.get(1)?,
                        project_path: row
                            .get::<_, Option<String>>(2)?
                            .filter(|value| !value.is_empty()),
                        // OpenCode auto-generates titles from conversation content.
                        title: None,
                    },
                    created_ms: row.get(3)?,
                })
            })
            .map_err(|error| error.to_string())?;
        for row in rows {
            let session = row.map_err(|error| error.to_string())?;
            sessions.insert(session.metadata.id.clone(), session);
        }
    }
    let steps = steps(&transaction)?;
    let legacy = messages(&transaction, false)?;
    let modern = messages(&transaction, true)?;
    let legacy_ids: std::collections::HashSet<_> =
        legacy.iter().map(|message| message.id.clone()).collect();
    let mut events = BTreeMap::new();
    for (is_modern, messages) in [(false, legacy), (true, modern)] {
        for message in messages {
            if is_modern && legacy_ids.contains(&message.id) {
                continue;
            }
            let Some(session) = sessions.get(&message.session_id) else {
                continue;
            };
            // Fork copies retain original creation times but receive new IDs. They
            // are historical context, not new requests charged to the new session.
            if message.created_ms > 0 && message.created_ms < session.created_ms {
                continue;
            }
            let record = |event: CoreResult<Option<UsageEvent>>,
                          events: &mut BTreeMap<String, UsageEvent>,
                          warnings: &mut Vec<String>| {
                match event {
                    Ok(Some(mut event)) => {
                        if let Some(bounds) = &mut event.uncertain_time {
                            bounds.since_ms = (session.created_ms > 0).then_some(session.created_ms);
                        }
                        event.incomplete |= event.uncertain_time.is_some();
                        events.insert(event.id.clone(), event);
                    }
                    Ok(None) => {}
                    Err(error) => warnings.push(format!("OpenCode usage: {error}")),
                }
            };
            if !is_modern && steps.contains_key(&message.id) {
                for (index, step) in steps[&message.id].iter().enumerate() {
                    let id = if index == 0 {
                        format!("message:{}", message.id)
                    } else {
                        format!("step:{}", step.id)
                    };
                    record(
                        event(
                            &message,
                            id,
                            message.created_ms.max(step.created_ms),
                            message.updated_ms.max(step.updated_ms),
                            &step.usage,
                        ),
                        &mut events,
                        &mut report.warnings,
                    );
                }
            } else {
                record(
                    event(
                        &message,
                        format!("message:{}", message.id),
                        message.created_ms,
                        message.updated_ms,
                        &message.usage,
                    ),
                    &mut events,
                    &mut report.warnings,
                );
            }
        }
    }
    transaction.commit().map_err(|error| error.to_string())?;
    let sessions: Vec<_> = sessions
        .into_values()
        .map(|session| session.metadata)
        .collect();
    let events: Vec<_> = events.into_values().collect();
    // Hash only projected metadata, not database bytes (which include bodies).
    // Rechecking the projection catches in-place updates even when main-db mtime
    // is unchanged because the writer has only appended to its WAL.
    let encoded = serde_json::to_vec(&(&sessions, &events)).map_err(|error| error.to_string())?;
    let hash = format!("{:x}", Sha256::digest(encoded));
    let identity = format!("opencode:{}", path.display());
    let previous = store.load_cursor(&identity)?;
    let reparse = previous.as_ref().is_some_and(|old|
        old.parser_state.get("analysis_version").and_then(|value|value.as_u64()) != Some(crate::parsers::ANALYSIS_VERSION));
    if !reparse && previous.is_some_and(|cursor| cursor.head_hash == hash)
    {
        return Ok(());
    }
    let cursor = SourceCursor {
        identity,
        path: path.display().to_string(),
        offset: 0,
        length: events.len() as u64,
        modified_ns: report.checked_at_ms.to_string(),
        head_hash: hash,
        parser_state: json!({"generation": 1,"analysis_version":crate::parsers::ANALYSIS_VERSION}),
    };
    if reparse {
        store.reparse_source(&cursor, &sessions, &events, &[])?;
    } else {
        store.commit_source(&cursor, &sessions, &events, &[])?;
    }
    report.files_changed += 1;
    report.events_upserted += events.len();
    Ok(())
}
