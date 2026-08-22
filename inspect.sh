#!/usr/bin/env bash
# Guarded wrapper for one inspect child process.
#
# Every mode uses the project-local runtime/bin/python3.12 interpreter.
# --local executes the direct collector; remote real mode launches the bundled
# Ansible runtime; fixture/query modes never contact a host.
set -u

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  echo "inspect.sh: error: sourcing is unsupported; run it as a standalone process" >&2
  return 10 2>/dev/null || exit 10
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="$SCRIPT_DIR/runtime"

# A wrapper-owned sentinel proves that normal/error/signal exits all pass
# through cleanup. It contains no environment, command line, or secret.
SESSION_FILE="$(mktemp "${TMPDIR:-/tmp}/inspect-wrapper.XXXXXX")" || {
  echo "inspect.sh: execution failed: cannot create cleanup sentinel" >&2
  exit 10
}
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if ! rm -f -- "$SESSION_FILE"; then
    echo "inspect.sh: cleanup diagnostic: wrapper sentinel removal failed" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

is_query=0
is_local=0
is_remote=0
for arg in "$@"; do
  case "$arg" in
    --list-metrics|--info) is_query=1 ;;
    --local) is_local=1 ;;
    -H|--hosts|-i|--inventory) is_remote=1 ;;
  esac
done
# The option value is a separate argv element for -H/--hosts/-i/--inventory;
# detect those forms without parsing or rewriting the CLI arguments.
if [ "$is_query" -eq 0 ]; then
  for arg in "$@"; do
    case "$arg" in
      -H=*|--hosts=*|-i=*|--inventory=*) is_remote=1 ;;
    esac
  done
  if [ "$is_remote" -eq 0 ]; then is_local=1; fi
fi

fixture_mode="${INSPECT_FIXTURE_DIR:-}"
# Select the interpreter by host OS, not by executable bits alone: the Linux
# binary must be executable after a Git checkout, but that bit must not make a
# Windows Git Bash host select an ELF binary over the companion .exe.
HOST_OS="$(uname -s 2>/dev/null || printf '%s' "${OSTYPE:-unknown}")"
case "$HOST_OS" in
  MINGW*|MSYS*|CYGWIN*|mingw*|msys*|cygwin*)
    PY="$RUNTIME_ROOT/bin/python3.12.exe"
    ;;
  *)
    PY="$RUNTIME_ROOT/bin/python3.12"
    ;;
esac
if [ ! -x "$PY" ]; then
  echo "inspect.sh: execution failed: project-local Python 3.12 is missing; system Python fallback is forbidden" >&2
  exit 10
fi
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
  echo "inspect.sh: execution failed: project-local Python is not 3.12.x; fallback is forbidden" >&2
  exit 10
fi
if [ -z "$fixture_mode" ] && [ "$is_query" -eq 0 ]; then
  if [ "$is_local" -eq 1 ]; then
    # --local uses the direct project-local collector; it must never enter
    # the Ansible gate, even when a caller inherited real-execution variables.
    unset INSPECT_ENABLE_REAL INSPECT_ENABLE_LOCAL_REAL INSPECT_REMOTE_USER INSPECT_ASK_PASS
  else
    # Remote -H/--hosts and -i/--inventory use the bundled Ansible runtime.
    # The gate is scoped to this process and contains no credential value.
    export INSPECT_ENABLE_REAL=1
  fi
else
  # Fixture and query modes must not inherit a real-execution gate.
  unset INSPECT_ENABLE_REAL INSPECT_ENABLE_LOCAL_REAL INSPECT_REMOTE_USER INSPECT_ASK_PASS
fi

# Never pass common password values to Ansible. INSPECT_ASK_PASS is only a
# non-secret boolean flag and, for remote mode, remains caller-controlled.
unset ANSIBLE_PASSWORD ANSIBLE_NET_PASSWORD SSHPASS
export INSPECT_RUNTIME_ROOT="$RUNTIME_ROOT"
export PYTHONPATH="$SCRIPT_DIR"

# Do not use exec: EXIT cleanup must run after normal and failed child exits.
if [[ "$PY" == *.exe ]]; then
  # The Windows embeddable runtime puts stdlib inspect.py in python312.zip.
  # Load this project's inspect package explicitly so its compatibility layer
  # can then absorb the stdlib module without allowing the zip to shadow it.
  "$PY" -c 'import importlib.util, os, runpy, sys; root=os.path.dirname(os.environ["INSPECT_RUNTIME_ROOT"]); package=os.path.join(root, "inspect"); spec=importlib.util.spec_from_file_location("inspect", os.path.join(package, "__init__.py"), submodule_search_locations=[package]); module=importlib.util.module_from_spec(spec); sys.modules["inspect"]=module; spec.loader.exec_module(module); sys.argv=["inspect.cli", *sys.argv[1:]]; runpy.run_module("inspect.cli", run_name="__main__")' "$@"
else
  "$PY" -m inspect.cli "$@"
fi
status=$?
exit "$status"
