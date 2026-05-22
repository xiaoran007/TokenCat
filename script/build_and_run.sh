#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="TokenCatMac"
BUNDLE_ID="com.xiaoran.tokencat.dev"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PATH="$ROOT_DIR/macos/TokenCatMac/TokenCatMac.xcodeproj"
SCHEME="TokenCatMac"
DERIVED_DATA_PATH="$ROOT_DIR/build/macos-derived"
APP_BUNDLE="$DERIVED_DATA_PATH/Build/Products/Debug/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
PYTHON_BIN="${TOKENCAT_PYTHON:-$ROOT_DIR/.venv/bin/python}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"

if ! xcrun --find xcodebuild >/dev/null 2>&1; then
  echo "xcodebuild is unavailable. Install full Xcode and run: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  exit 69
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "TokenCat Python executable is missing or not executable: $PYTHON_BIN" >&2
  exit 66
fi

build_settings=()
if [[ -n "${TOKENCAT_DEVELOPMENT_TEAM:-}" ]]; then
  build_settings+=("DEVELOPMENT_TEAM=$TOKENCAT_DEVELOPMENT_TEAM")
fi

build_app() {
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  local command=(
    xcodebuild
    -project "$PROJECT_PATH"
    -scheme "$SCHEME"
    -configuration Debug
    -derivedDataPath "$DERIVED_DATA_PATH"
  )
  if [[ "${#build_settings[@]}" -gt 0 ]]; then
    command+=("${build_settings[@]}")
  fi
  command+=(
    build
  )
  "${command[@]}"
}

open_app() {
  launchctl setenv TOKENCAT_ROOT "$ROOT_DIR"
  launchctl setenv TOKENCAT_PYTHON "$PYTHON_BIN"
  /usr/bin/open -n "$APP_BUNDLE"
}

case "$MODE" in
  run)
    build_app
    open_app
    ;;
  --debug|debug)
    build_app
    launchctl setenv TOKENCAT_ROOT "$ROOT_DIR"
    launchctl setenv TOKENCAT_PYTHON "$PYTHON_BIN"
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    build_app
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    build_app
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    build_app
    open_app
    sleep 1
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
