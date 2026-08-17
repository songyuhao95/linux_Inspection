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
ANSIBLE_SITE="$STAGE/ansible/site-packages"
ANSIBLE_COLLECTIONS="$STAGE/ansible/collections"
if [ ! -x "$PY" ]; then
  echo "build-runtime.sh: archive must contain executable bin/python3.12" >&2
  exit 10
fi
if [ ! -f "$ANSIBLE_SITE/ansible/__init__.py" ] || \
   [ ! -f "$ANSIBLE_SITE/ansible/cli/playbook.py" ]; then
  echo "build-runtime.sh: archive must contain ansible/site-packages/ansible and ansible.cli.playbook" >&2
  exit 10
fi
if [ ! -d "$ANSIBLE_COLLECTIONS" ]; then
  echo "build-runtime.sh: archive must contain ansible/collections" >&2
  exit 10
fi
VERSION="$($PY -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
case "$VERSION" in
  3.12.*) ;;
  *) echo "build-runtime.sh: archive interpreter reports $VERSION, need 3.12.x" >&2; exit 10 ;;
esac
ANSIBLE_VERSION="$(PYTHONPATH="$ANSIBLE_SITE" PYTHONNOUSERSITE=1 "$PY" -c 'import importlib.metadata; import ansible.cli.playbook; print(importlib.metadata.version("ansible-core"))')" || {
  echo "build-runtime.sh: bundled ansible-core metadata or entry point is invalid" >&2
  exit 10
}
ANSIBLE_PATH="$(PYTHONPATH="$ANSIBLE_SITE" PYTHONNOUSERSITE=1 "$PY" -c 'import ansible; print(ansible.__file__)')"
case "$ANSIBLE_PATH" in
  "$ANSIBLE_SITE"/*) ;;
  *) echo "build-runtime.sh: ansible resolved outside the archive bundle" >&2; exit 10 ;;
esac
PY_HASH="$(sha256sum "$PY" | awk '{print $1}')"
BUNDLE_HASH="$($PY - "$STAGE/ansible" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
h = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    h.update(str(path.relative_to(root)).encode("utf-8"))
    h.update(b"\0")
    h.update(path.read_bytes())
    h.update(b"\0")
print(h.hexdigest())
PY
)"
"$PY" - "$RUNTIME_DIR/manifest.json" "$PY_HASH" "$VERSION" "$ANSIBLE_VERSION" "$BUNDLE_HASH" <<'PY'
import json
import pathlib
import sys
manifest_path = pathlib.Path(sys.argv[1])
data = json.loads(manifest_path.read_text(encoding="utf-8"))
data["status"] = "built"
data["python"]["sha256"] = sys.argv[2]
data["python"]["version"] = "3.12.x"
data["build_version"] = sys.argv[3]
data["ansible"]["status"] = "built"
data["ansible"]["version"] = sys.argv[4]
data["ansible"]["bundle_sha256"] = sys.argv[5]
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
echo "runtime materialized: Python $VERSION, ansible-core $ANSIBLE_VERSION (python sha256=$PY_HASH, bundle sha256=$BUNDLE_HASH)"
