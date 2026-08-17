#!/usr/bin/env bash
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "build-runtime.sh: usage: $0 APPROVED_OFFLINE_RUNTIME_ARCHIVE" >&2
  exit 2
fi
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/inspect-runtime.XXXXXX")"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT HUP INT TERM
case "$ARCHIVE" in
  *.tar.gz|*.tgz) tar -xzf "$ARCHIVE" -C "$STAGE" ;;
  *.tar) tar -xf "$ARCHIVE" -C "$STAGE" ;;
  *) echo "build-runtime.sh: only .tar or .tar.gz archives are accepted" >&2; exit 2 ;;
esac
PY="$STAGE/bin/python3.12"
if [ ! -x "$PY" ]; then
  echo "build-runtime.sh: archive must contain executable bin/python3.12" >&2
  exit 10
fi
VERSION="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
case "$VERSION" in
  3.12.*) ;;
  *) echo "build-runtime.sh: archive interpreter reports $VERSION, need 3.12.x" >&2; exit 10 ;;
esac
HASH="$(sha256sum "$PY" | awk '{print $1}')"
"$PY" - "$RUNTIME_DIR/manifest.json" "$HASH" "$VERSION" <<'PY'
import json, pathlib, sys
manifest_path = pathlib.Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
data["status"] = "built"
data["python"]["sha256"] = sys.argv[2]
data["python"]["version"] = "3.12.x"
data["build_version"] = sys.argv[3]
manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
mkdir -p "$RUNTIME_DIR"
rm -rf -- "$RUNTIME_DIR/.stage"
mkdir "$RUNTIME_DIR/.stage"
cp -a "$STAGE"/. "$RUNTIME_DIR/.stage/"
for item in "$RUNTIME_DIR/.stage"/*; do
  [ -e "$item" ] || continue
  target="$RUNTIME_DIR/$(basename "$item")"
  rm -rf -- "$target"
  mv "$item" "$target"
done
rmdir "$RUNTIME_DIR/.stage"
echo "runtime materialized: Python $VERSION (sha256=$HASH)"
