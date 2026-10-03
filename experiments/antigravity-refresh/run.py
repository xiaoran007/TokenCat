"""Run isolated, offline Rust experiments; never overwrite the app's core/library."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

BLOB_READ = '''        let mut slot = self.blob.borrow_mut();
        if slot.is_none() {
            *slot = Some(self.connection.blob_open(
                "main", self.table, self.column, self.index, true
            ).map_err(|e| e.to_string())?);
        }
        let mut bytes = vec![0; range.len()];
        slot.as_ref().unwrap().read_at_exact(&mut bytes, range.start)
            .map_err(|e| e.to_string())?;
        Ok(bytes)
'''

CACHE = '''
// Experiment only: production should own and prune this cache in Engine.
struct CachedDatabase {
    identity: (u64, u64),
    connection: Connection,
    snapshot: Option<(i64, DatabaseUsage, Vec<String>)>,
}
thread_local! {
    static DATABASES: std::cell::RefCell<BTreeMap<PathBuf, CachedDatabase>> =
        std::cell::RefCell::new(BTreeMap::new());
}
fn read_database(path: &Path, report: &mut ScanReport) -> CoreResult<DatabaseUsage> {
    use std::os::unix::fs::MetadataExt;
    let metadata = fs::metadata(path).map_err(|e| e.to_string())?;
    let identity = (metadata.dev(), metadata.ino());
    DATABASES.with(|databases| {
        let mut databases = databases.borrow_mut();
        if databases.get(path).is_none_or(|old| old.identity != identity) {
            databases.remove(path);
            let connection = Connection::open_with_flags(path,
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
                .map_err(|e| e.to_string())?;
            connection.busy_timeout(Duration::from_millis(250)).map_err(|e| e.to_string())?;
            databases.insert(path.to_owned(), CachedDatabase { identity, connection, snapshot: None });
        }
        let cached = databases.get_mut(path).unwrap();
        let revision = |connection: &Connection| -> CoreResult<i64> {
            connection.query_row("PRAGMA data_version", [], |row| row.get(0))
                .map_err(|e| e.to_string())
        };
        let before = revision(&cached.connection)?;
        if let Some((version, data, warnings)) = &cached.snapshot {
            if *version == before {
                report.warnings.extend(warnings.clone());
                return Ok(data.clone());
            }
        }
        // Clear on error/change; never silently reuse an invalid snapshot.
        cached.snapshot = None;
        let mut local = ScanReport::default();
        let data = read_database_uncached(path, &cached.connection, &mut local)?;
        if revision(&cached.connection)? == before {
            cached.snapshot = Some((before, data.clone(), local.warnings.clone()));
        }
        report.warnings.extend(local.warnings);
        Ok(data)
    })
}
'''


def replace_once(source, old, new):
    assert source.count(old) == 1, f"Prototype patch no longer matches: {old[:80]}"
    return source.replace(old, new, 1)


def prototype(source, variant):
    if variant == "baseline":
        return source
    source = replace_once(source, "use rusqlite::{params, Connection, OpenFlags};", "use rusqlite::{Connection, OpenFlags};")
    source = replace_once(source, "    length: usize,\n}\nimpl MetadataReader", 
                          "    length: usize,\n    blob: std::cell::RefCell<Option<rusqlite::blob::Blob<'a>>>,\n}\nimpl MetadataReader")
    begin = source.index("        self.connection\n", source.index("impl MetadataReader"))
    end = source.index("\n    }\n    fn varint", begin)
    source = source[:begin] + BLOB_READ.rstrip() + source[end:]
    assert source.count("        length,\n    };") == 3
    source = source.replace("        length,\n    };", "        length,\n        blob: std::cell::RefCell::new(None),\n    };")
    if variant in ("cached", "bounded"):
        source = replace_once(source, "#[derive(Serialize)]\nstruct DatabaseUsage", "#[derive(Clone, Serialize)]\nstruct DatabaseUsage")
        begin = source.index("fn read_database(path:")
        end = source.index("    // One consistent WAL snapshot", begin)
        cache = CACHE
        if variant == "bounded":
            cache = replace_once(cache, "            connection.busy_timeout", 
                '            connection.execute_batch("PRAGMA cache_size=-256").map_err(|e| e.to_string())?;\n            connection.busy_timeout')
        source = source[:begin] + cache + "\nfn read_database_uncached(path: &Path, connection: &Connection, report: &mut ScanReport) -> CoreResult<DatabaseUsage> {\n" + source[end:]
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, help="Reuse an earlier isolated compilation cache")
    parser.add_argument("--variants", nargs="+", choices=("baseline", "blob", "cached", "bounded"),
                        default=("baseline", "blob", "cached", "bounded"))
    parser.add_argument("--resume", action="store_true", help="Load existing results before running selected variants")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="tokencat-refresh-experiment-"))
    assert not workspace.resolve().is_relative_to(ROOT), "Workspace must be outside the repository"
    print(f"Isolated workspace: {workspace}", flush=True)
    (args.output / "workspace.txt").write_text(str(workspace) + "\n")
    fixture = (ROOT / "native/tokencat-core/tests/antigravity.rs").read_text().split("#[test]", 1)[0]
    fixture = fixture.replace('bytes(1, b"PRIVATE PROMPT SENTINEL")', 'bytes(1, &vec![b\'P\'; PAYLOAD.load(Ordering::Relaxed) as usize])')
    results = json.loads((args.output / "results.json").read_text()) if args.resume else {}
    for variant in args.variants:
        destination = workspace / variant
        shutil.copytree(ROOT / "native", destination, ignore=shutil.ignore_patterns("target"), dirs_exist_ok=True)
        manifest = destination / "tokencat-core/Cargo.toml"
        if variant != "baseline":
            manifest.write_text(manifest.read_text().replace('features = ["bundled"]', 'features = ["bundled", "blob"]'))
        source = destination / "tokencat-core/src/antigravity.rs"
        source.write_text(prototype(source.read_text(), variant))
        (args.output / f"{variant}-antigravity.rs").write_text(source.read_text())
        examples = destination / "tokencat-core/examples"
        examples.mkdir(exist_ok=True)
        (examples / "refresh_benchmark.rs").write_text(fixture + (HERE / "benchmark.rs").read_text())
        cargo = ["cargo", "--offline", "--locked"]
        # Distinct target directory: no writes to native/target or macos/.build.
        target = workspace / "target"
        for command in ("test", "build"):
            options = [] if command == "test" else ["--example", "refresh_benchmark"]
            with (args.output / f"{variant}-{command}.log").open("w") as log:
                subprocess.run([*cargo, command, "--release", "--manifest-path", str(destination / "Cargo.toml"),
                                "--target-dir", str(target), *options], stdout=log, stderr=subprocess.STDOUT, check=True)
            print(f"{variant}: {command} passed", flush=True)
        results[variant] = []
        for profile in ("small", "large"):
            measured = subprocess.run(["/usr/bin/time", "-l", str(target / "release/examples/refresh_benchmark"), profile],
                                      capture_output=True, text=True, check=True)
            (args.output / f"{variant}-{profile}-time.txt").write_text(measured.stderr)
            peak = int(re.search(r"(\d+)\s+maximum resident set size", measured.stderr)[1])
            rows = [json.loads(line) for line in measured.stdout.splitlines()]
            for row in rows:
                row["process_peak_rss_bytes"] = peak
            results[variant].extend(rows)
            (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"{variant} {profile}: " + ", ".join(
                f'{row["scenario"]}={row["wall_ms_median"]:.3f}ms' for row in rows), flush=True)
    baseline = [(row["profile"], row["scenario"], row["digest"], row["events"]) for row in results["baseline"]]
    for variant in results.keys() - {"baseline"}:
        assert [(row["profile"], row["scenario"], row["digest"], row["events"]) for row in results[variant]] == baseline, variant
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("All variants produced identical events, session metadata, and scan reports in all scenarios.", flush=True)


if __name__ == "__main__":
    main()
