use crate::model::*;
use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{de::DeserializeOwned, Serialize};
use std::{path::Path, time::Duration};

pub struct Store {
    connection: Connection,
}

fn encoded<T: Serialize>(value: &T) -> CoreResult<String> {
    serde_json::to_string(value).map_err(|error| error.to_string())
}

fn decoded<T: DeserializeOwned>(value: String) -> CoreResult<T> {
    serde_json::from_str(&value).map_err(|error| error.to_string())
}

impl Store {
    pub fn open(path: &Path) -> CoreResult<Self> {
        if let Some(parent) = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let connection = Connection::open(path).map_err(|error| error.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
                .map_err(|error| error.to_string())?;
        }
        connection
            .busy_timeout(Duration::from_secs(5))
            .map_err(|error| error.to_string())?;
        let version: u32 = connection
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .map_err(|error| error.to_string())?;
        if version > 1 {
            return Err(format!("Unsupported database schema version {version}"));
        }
        connection.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=FULL;
             PRAGMA foreign_keys=ON;
             BEGIN IMMEDIATE;
             CREATE TABLE IF NOT EXISTS cursors(identity TEXT PRIMARY KEY, path TEXT NOT NULL, payload TEXT NOT NULL);
             CREATE INDEX IF NOT EXISTS cursors_path ON cursors(path);
             CREATE TABLE IF NOT EXISTS sessions(provider TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(provider,id));
             CREATE TABLE IF NOT EXISTS events(provider TEXT NOT NULL, id TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, revision_ms INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(provider,id));
             CREATE INDEX IF NOT EXISTS events_timestamp ON events(timestamp_ms);
             CREATE TABLE IF NOT EXISTS states(provider TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL, timestamp_ms INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(provider,session_id,kind));
             CREATE TABLE IF NOT EXISTS source_events(identity TEXT NOT NULL, provider TEXT NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY(identity,provider,event_id));
             CREATE TABLE IF NOT EXISTS source_states(identity TEXT NOT NULL, provider TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(identity,provider,session_id,kind));
             CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, payload TEXT NOT NULL);
             PRAGMA user_version=1;
             COMMIT;"
        ).map_err(|error| error.to_string())?;
        Ok(Self { connection })
    }

    pub fn load_cursor(&self, identity: &str) -> CoreResult<Option<SourceCursor>> {
        let payload = self
            .connection
            .query_row(
                "SELECT payload FROM cursors WHERE identity=?1",
                [identity],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        payload.map(decoded).transpose()
    }

    /// Usage, parser state and offset become durable in one transaction.
    pub fn commit_source(
        &self,
        cursor: &SourceCursor,
        sessions: &[SessionMetadata],
        events: &[UsageEvent],
        states: &[ObservedState],
    ) -> CoreResult<()> {
        let transaction = self
            .connection
            .unchecked_transaction()
            .map_err(|error| error.to_string())?;
        let old: Option<String> = transaction
            .query_row(
                "SELECT payload FROM cursors WHERE identity=?1",
                [&cursor.identity],
                |row| row.get(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        if let Some(old) = old {
            let previous: SourceCursor = decoded(old)?;
            if generation(&previous) != generation(cursor) {
                retire_source(&transaction, &cursor.identity)?;
            }
        }
        let retired = {
            let mut statement = transaction
                .prepare("SELECT identity FROM cursors WHERE path=?1 AND identity<>?2")
                .map_err(|error| error.to_string())?;
            let rows = statement
                .query_map(params![cursor.path, cursor.identity], |row| {
                    row.get::<_, String>(0)
                })
                .map_err(|error| error.to_string())?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(|error| error.to_string())?
        };
        for identity in retired {
            retire_source(&transaction, &identity)?;
        }
        for session in sessions {
            transaction.execute("INSERT INTO sessions(provider,id,payload) VALUES(?1,?2,?3) ON CONFLICT(provider,id) DO UPDATE SET payload=excluded.payload", params![session.provider.as_str(), session.id, encoded(session)?]).map_err(|error| error.to_string())?;
        }
        for event in events {
            let mut revised = event.clone();
            let timestamp: Option<i64> = transaction
                .query_row(
                    "SELECT timestamp_ms FROM events WHERE provider=?1 AND id=?2",
                    params![event.provider.as_str(), event.id],
                    |row| row.get(0),
                )
                .optional()
                .map_err(|error| error.to_string())?;
            if let Some(timestamp) = timestamp {
                revised.timestamp_ms = timestamp;
            }
            transaction.execute("INSERT INTO events(provider,id,timestamp_ms,revision_ms,payload) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(provider,id) DO UPDATE SET revision_ms=excluded.revision_ms,payload=excluded.payload WHERE excluded.revision_ms>=events.revision_ms", params![revised.provider.as_str(), revised.id, revised.timestamp_ms, event.revision_ms.unwrap_or(event.timestamp_ms), encoded(&revised)?]).map_err(|error| error.to_string())?;
            transaction.execute("INSERT OR IGNORE INTO source_events(identity,provider,event_id) VALUES(?1,?2,?3)", params![cursor.identity, event.provider.as_str(), event.id]).map_err(|error| error.to_string())?;
        }
        for state in states {
            transaction.execute("INSERT INTO states(provider,session_id,kind,timestamp_ms,payload) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(provider,session_id,kind) DO UPDATE SET timestamp_ms=excluded.timestamp_ms,payload=excluded.payload WHERE excluded.timestamp_ms>=states.timestamp_ms", params![state.provider.as_str(), state.session_id, state.kind, state.timestamp_ms, encoded(state)?]).map_err(|error| error.to_string())?;
            transaction.execute("INSERT OR IGNORE INTO source_states(identity,provider,session_id,kind) VALUES(?1,?2,?3,?4)", params![cursor.identity, state.provider.as_str(), state.session_id, state.kind]).map_err(|error| error.to_string())?;
        }
        transaction.execute("INSERT INTO cursors(identity,path,payload) VALUES(?1,?2,?3) ON CONFLICT(identity) DO UPDATE SET path=excluded.path,payload=excluded.payload", params![cursor.identity, cursor.path, encoded(cursor)?]).map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())
    }

    pub fn save_scan(&self, report: &ScanReport) -> CoreResult<()> {
        self.connection.execute("INSERT INTO metadata(key,payload) VALUES('last_scan',?1) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", [encoded(report)?]).map_err(|error| error.to_string())?;
        Ok(())
    }

    /// Consolidate identities only after the adapter has observed evidence that
    /// they refer to the same request. Missing source files never trigger this.
    pub fn merge_event_ids(
        &self,
        provider: Provider,
        canonical: &str,
        retired: &[String],
    ) -> CoreResult<()> {
        let transaction = self.connection.unchecked_transaction().map_err(|e| e.to_string())?;
        let mut best: Option<(i64, UsageEvent)> = None;
        let mut earliest: Option<i64> = None;
        for id in std::iter::once(canonical).chain(retired.iter().map(String::as_str)) {
            let row: Option<(i64, i64, String)> = transaction.query_row(
                "SELECT timestamp_ms,revision_ms,payload FROM events WHERE provider=?1 AND id=?2",
                params![provider.as_str(), id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            ).optional().map_err(|e| e.to_string())?;
            if let Some((timestamp, revision, payload)) = row {
                earliest = Some(earliest.map_or(timestamp, |old| old.min(timestamp)));
                let event: UsageEvent = decoded(payload)?;
                if best.as_ref().is_none_or(|(old_revision, _)| revision > *old_revision) {
                    best = Some((revision, event));
                }
            }
        }
        if let Some((revision, mut event)) = best {
            event.id = canonical.into();
            event.timestamp_ms = earliest.expect("a stored event has a timestamp");
            transaction.execute(
                "INSERT INTO events(provider,id,timestamp_ms,revision_ms,payload) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(provider,id) DO UPDATE SET timestamp_ms=excluded.timestamp_ms,revision_ms=excluded.revision_ms,payload=excluded.payload",
                params![provider.as_str(), canonical, event.timestamp_ms, revision, encoded(&event)?],
            ).map_err(|e| e.to_string())?;
            for id in retired.iter().filter(|id| id.as_str() != canonical) {
                transaction.execute(
                    "INSERT OR IGNORE INTO source_events(identity,provider,event_id) SELECT identity,provider,?1 FROM source_events WHERE provider=?2 AND event_id=?3",
                    params![canonical, provider.as_str(), id],
                ).map_err(|e| e.to_string())?;
                transaction.execute("DELETE FROM source_events WHERE provider=?1 AND event_id=?2",
                    params![provider.as_str(), id]).map_err(|e| e.to_string())?;
                transaction.execute("DELETE FROM events WHERE provider=?1 AND id=?2",
                    params![provider.as_str(), id]).map_err(|e| e.to_string())?;
            }
        }
        transaction.commit().map_err(|e| e.to_string())
    }

    fn records<T: DeserializeOwned>(&self, sql: &str) -> CoreResult<Vec<T>> {
        let mut statement = self
            .connection
            .prepare(sql)
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        rows.map(|row| decoded(row.map_err(|error| error.to_string())?))
            .collect()
    }

    pub fn events(&self) -> CoreResult<Vec<UsageEvent>> {
        self.records("SELECT payload FROM events ORDER BY timestamp_ms,provider,id")
    }
    pub fn events_between(&self, since: i64, until: i64) -> CoreResult<Vec<UsageEvent>> {
        let mut statement = self.connection.prepare("SELECT payload FROM events WHERE timestamp_ms>=?1 AND timestamp_ms<?2 ORDER BY timestamp_ms,provider,id").map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![since, until], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        rows.map(|row| decoded(row.map_err(|error| error.to_string())?))
            .collect()
    }
    pub fn sessions(&self) -> CoreResult<Vec<SessionMetadata>> {
        self.records("SELECT payload FROM sessions ORDER BY provider,id")
    }
    pub fn states(&self) -> CoreResult<Vec<ObservedState>> {
        self.records("SELECT payload FROM states ORDER BY provider,session_id,kind")
    }
    pub fn last_scan(&self) -> CoreResult<Option<ScanReport>> {
        let payload = self
            .connection
            .query_row(
                "SELECT payload FROM metadata WHERE key='last_scan'",
                [],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        payload.map(decoded).transpose()
    }
}

fn generation(cursor: &SourceCursor) -> u64 {
    cursor
        .parser_state
        .get("generation")
        .and_then(|value| value.as_u64())
        .unwrap_or(0)
}

fn retire_source(transaction: &Transaction<'_>, identity: &str) -> CoreResult<()> {
    for table in ["source_events", "source_states", "cursors"] {
        transaction
            .execute(
                &format!("DELETE FROM {table} WHERE identity=?1"),
                [identity],
            )
            .map_err(|error| error.to_string())?;
    }
    // Provider logs may be rotated or deleted. They are not the retention
    // authority for the user's ledger; stable event IDs reconcile replay.
    Ok(())
}
