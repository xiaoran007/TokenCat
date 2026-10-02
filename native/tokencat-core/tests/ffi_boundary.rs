use std::ffi::{CStr, CString};
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};
use tokencat_core::ffi::*;

unsafe fn take_json(pointer: *mut std::ffi::c_char) -> serde_json::Value {
    assert!(!pointer.is_null());
    let value = serde_json::from_str(CStr::from_ptr(pointer).to_str().unwrap()).unwrap();
    tokencat_string_free(pointer);
    value
}

#[test]
fn app_boundary_persists_usage_across_reopen_and_returns_query_errors() {
    let root = std::env::temp_dir().join(format!(
        "tokencat-ffi-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let projects = root.join(".claude/projects/example");
    fs::create_dir_all(&projects).unwrap();
    fs::write(projects.join("session.jsonl"), concat!(
        "{\"type\":\"assistant\",\"sessionId\":\"session\",\"timestamp\":\"2026-10-02T12:00:00Z\",",
        "\"message\":{\"id\":\"message\",\"role\":\"assistant\",\"model\":\"claude-sonnet-4-6\",",
        "\"usage\":{\"input_tokens\":100,\"cache_read_input_tokens\":900,\"cache_creation_input_tokens\":0,\"output_tokens\":50}}}\n"
    )).unwrap();
    let config = CString::new(
        serde_json::json!({
            "home": root, "database_path": root.join("state/usage.sqlite"),
            "codex_root": null, "claude_roots": [], "pricing_path": null
        })
        .to_string(),
    )
    .unwrap();
    let query = CString::new(
        serde_json::json!({
            "since_ms": 1790899200000_i64, "until_ms": 1790985600000_i64,
            "timezone": "America/New_York", "show_paths": false
        })
        .to_string(),
    )
    .unwrap();
    unsafe {
        let handle = tokencat_open(config.as_ptr());
        assert!(!handle.is_null(), "{}", take_json(tokencat_last_error()));
        let scan = take_json(tokencat_scan(handle));
        assert_eq!(scan["ok"], true);
        assert_eq!(scan["data"]["events_upserted"], 1);
        let dashboard = take_json(tokencat_query(handle, query.as_ptr()));
        assert_eq!(dashboard["ok"], true);
        assert_eq!(dashboard["data"]["summary"]["event_count"], 1);
        assert_eq!(dashboard["data"]["summary"]["cache_read_tokens"], 900);
        assert!(
            dashboard["data"]["summary"]["cost"]["min_usd"]
                .as_f64()
                .unwrap()
                > 0.0
        );
        tokencat_close(handle);

        let reopened = tokencat_open(config.as_ptr());
        assert!(!reopened.is_null());
        let unchanged = take_json(tokencat_scan(reopened));
        assert_eq!(unchanged["data"]["events_upserted"], 0);
        let dashboard = take_json(tokencat_query(reopened, query.as_ptr()));
        assert_eq!(dashboard["data"]["summary"]["event_count"], 1);
        let invalid =
            CString::new("{\"since_ms\":0,\"until_ms\":1,\"timezone\":\"invalid\"}").unwrap();
        assert_eq!(
            take_json(tokencat_query(reopened, invalid.as_ptr()))["ok"],
            false
        );
        tokencat_close(reopened);
    }
    fs::remove_dir_all(root).unwrap();
}
