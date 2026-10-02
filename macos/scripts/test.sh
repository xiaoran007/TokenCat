#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/../.." && pwd)"
artifact_log="$(mktemp -t tokencat-tests.XXXXXX)"
trap 'rm -f "$artifact_log"' EXIT

export MACOSX_DEPLOYMENT_TARGET=14.0
cargo test --locked --release --message-format=json-render-diagnostics \
  --manifest-path "$project_root/native/Cargo.toml" > "$artifact_log" || {
    cat "$artifact_log"
    exit 1
  }
swift "$project_root/macos/scripts/prepare-test-library.swift" \
  "$artifact_log" "$project_root/native/target/release/libtokencat_core.a"
echo "Rust tests passed. Testing Swift models, localization, and app compilation."
swift test --package-path "$project_root/macos" "$@"
