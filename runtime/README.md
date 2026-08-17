# Project-local Python 3.12 runtime

`runtime/` is a contract, not a promise that the repository contains a binary.
The checked-in manifest deliberately starts in `not-built` state. Real
execution fails closed until an administrator supplies an approved offline
Python 3.12 archive and its matching Ansible control-side dependencies.

## Layout

```text
runtime/
  manifest.json
  bin/python3.12
```

The interpreter must report Python `3.12.x`. The manifest records the expected
relative path, platform scope, Ansible module entry point, and (after build) the
SHA-256 of the interpreter artifact. `inspect.sh` never falls back to
`python3`, `python`, or a PATH `ansible-playbook` for real execution.

## Offline materialization

Use `tools/build-runtime.sh /path/to/approved-python312-runtime.tar.*` on the
same platform as the target. The archive must already contain the interpreter
and the pinned Ansible/YAML/reporting dependencies; the tool does not download,
install, or invoke a package manager. It extracts to a staging directory,
checks that `bin/python3.12` reports 3.12, writes the interpreter hash into the
manifest, and atomically replaces `runtime/bin`.

The binary must be checked against the approved release artifact and tested on
the target's CPU architecture and glibc baseline. A Linux binary built for a
newer glibc is not considered portable to Kylin V10 merely because its filename
is `python3.12`.

## Execution contract

- Fixture mode (`INSPECT_FIXTURE_DIR=...`) and query-only commands do not invoke
  Ansible and may run with the caller's interpreter for local tests.
- Real mode requires the project-local interpreter and runs Ansible as
  `python3.12 -m ansible.cli.playbook`; no PATH lookup is permitted.
- Missing, non-executable, hash-mismatched, or non-3.12 runtimes return technical
  failure code 10 with a sanitized diagnostic.
- Runtime installation is never attempted during inspection.
