#!/usr/bin/env bash
# Guarded wrapper for one inspect child process.
#
# Real execution is fail-closed: only runtime/bin/python3.12 is accepted and
# Ansible is launched by that interpreter. Fixture/query paths intentionally do
# not require the binary because they never execute Ansible or contact a host.
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
if [ -n "$fixture_mode" ] || [ "$is_query" -eq 1 ]; then
  # Fixture mode has precedence over any inherited real gate. Query mode is
  # also non-real and must not require a runtime that cannot execute Ansible.
  unset INSPECT_ENABLE_REAL INSPECT_ENABLE_LOCAL_REAL INSPECT_REMOTE_USER INSPECT_ASK_PASS
  PY=""
  for cand in "${PYTHON3:-}" python3 python; do
    [ -n "$cand" ] || continue
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
      PY="$cand"
      break
    fi
  done
  if [ -z "$PY" ]; then
    echo "inspect.sh: execution failed: Python 3 was not found for fixture/query mode" >&2
    exit 10
  fi
else
  # Real execution must use the repository runtime. Never probe or fall back
  # to PATH Python, even when the project runtime has not been materialized.
  PY="$RUNTIME_ROOT/bin/python3.12"
  if [ ! -x "$PY" ]; then
    echo "inspect.sh: execution failed: project-local Python 3.12 is missing; system Python fallback is forbidden" >&2
    exit 10
  fi
  if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
    echo "inspect.sh: execution failed: project-local Python is not 3.12.x; fallback is forbidden" >&2
    exit 10
  fi
  # Internal non-secret gates are scoped to this process and its child only.
  export INSPECT_ENABLE_REAL=1
  if [ "$is_local" -eq 1 ]; then
    export INSPECT_ENABLE_LOCAL_REAL=1
    unset INSPECT_REMOTE_USER INSPECT_ASK_PASS
  fi
fi

# Never pass common password values to Ansible. INSPECT_ASK_PASS is only a
# non-secret boolean flag and, for remote mode, remains caller-controlled.
unset ANSIBLE_PASSWORD ANSIBLE_NET_PASSWORD SSHPASS
export INSPECT_RUNTIME_ROOT="$RUNTIME_ROOT"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Do not use exec: EXIT cleanup must run after normal and failed child exits.
"$PY" -m inspect.cli "$@"
status=$?
exit "$status"
