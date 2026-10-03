#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/../.." && pwd)"
app_path="$project_root/build/TokenCat.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The TokenCat app requires macOS." >&2
  exit 1
fi

export MACOSX_DEPLOYMENT_TARGET=14.0
cargo build --locked --release --manifest-path "$project_root/native/Cargo.toml"
swift build --package-path "$project_root/macos" --configuration release
swift_output="$(swift build --package-path "$project_root/macos" --configuration release --show-bin-path)"

mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
cp "$swift_output/TokenCat" "$app_path/Contents/MacOS/TokenCat"
cp "$project_root/macos/Info.plist" "$app_path/Contents/Info.plist"
cp "$project_root/macos/Branding/TokenCat.icns" "$app_path/Contents/Resources/"
cp -R "$swift_output/TokenCatMac_TokenCat.bundle" "$app_path/Contents/Resources/"
cp -R "$swift_output/TokenCatMac_TokenCatKit.bundle" "$app_path/Contents/Resources/"

# Local source builds use an ad-hoc signature; no publisher certificate is needed.
codesign --force --sign - "$app_path"
echo "Created $app_path"
