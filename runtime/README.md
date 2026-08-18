# Project-local Python 3.12 and Ansible runtime

`runtime/` is an offline, project-owned runtime contract. A source checkout may
start with a `not-built` manifest until an approved archive is materialized;
the deployable checkout in this branch records `status=built` and matching
hashes. Real execution fails closed while either the Python 3.12 interpreter or
the bundled Ansible package is missing or invalid.

## Required layout

```text
runtime/
  manifest.json
  bin/python3.12
  ansible/
    site-packages/ansible/__init__.py
    site-packages/ansible/cli/playbook.py
    collections/
```

The Linux report renderer dependencies are also committed in
`runtime/lib/python3.12/site-packages/`. The exact validated versions are listed
in `runtime/report-requirements.lock`; this includes `pandas`, `numpy`,
`xlsxwriter`, and their small pure-Python dependencies. A fresh supported Linux
checkout therefore does not need a separate `pip install` before using
`--excel` or `--html`. The checked-in tree is a Linux x86_64/CPython 3.12
artifact; it must not be copied into the Windows runtime.

The Linux deployment artifact is `runtime/bin/python3.12`. This repository also
ships a project-local Windows embeddable `runtime/bin/python3.12.exe` solely so
fixture and query commands use a project-owned 3.12 interpreter on Windows
workstations. It is not a substitute for the Linux runtime and cannot enable
real VM execution from Windows.

Both interpreters must report Python `3.12.x`. The Ansible control-side package
must be `ansible-core` and must import `ansible.cli.playbook` from the
project-local `runtime/ansible/site-packages` directory. The project does not
look up `ansible-playbook` on `PATH`, and it does not accept an Ansible import
resolved from a system Python, virtual environment, user site, or inherited
`PYTHONPATH`.

## Offline materialization

Use `tools/build-runtime.sh /path/to/approved-runtime.tar.gz` on the target
Linux platform. The archive must already contain both `bin/python3.12` and the
bundled Ansible tree shown above. The tool performs no network access, package
installation, or package-manager operation. It validates Python 3.12, imports
`ansible.cli.playbook` with only the archive site-packages path, records the
Python and Ansible bundle SHA-256 values in `manifest.json`, and atomically
materializes the archive contents below `runtime/`.

The archive must be produced from an approved offline dependency set. Validate
the binary against the target CPU architecture and glibc baseline; a file
named `python3.12` built for a newer glibc is not portable to Kylin V10 merely
because its filename matches.

See `runtime/ansible/README.md` and
`runtime/ansible/requirements.lock` for the bundle contract and dependency
range. The lock file is descriptive; the materializer never resolves or
downloads dependencies.

## Report CLI usage

The report flags are `--excel [PATH]` and `--html [PATH]`. When `PATH` is
omitted, the report is written to `Path.cwd()` using the inspection ID as the
filename; when supplied, the path is used directly. For example:

```bash
bash inspect.sh --local --excel --html
bash inspect.sh --local --excel reports/local.xlsx --html reports/local.html
```

The legacy `--xlsx-out` and `--html-out` options are no longer accepted.

## Environment and execution contract

- Fixture mode (`INSPECT_FIXTURE_DIR=...`) and query-only commands still use the
  project-local interpreter, do not invoke Ansible, and do not contact a host.
- Every wrapper invocation fails closed if the project-local Python 3.12 runtime
  is missing or invalid; no system Python fallback is permitted.
- Before spawning Ansible, the runner removes inherited Python and Ansible path
  variables (`PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`, `ANSIBLE_*` plugin
  paths, and collection paths), sets `PYTHONNOUSERSITE=1`, then sets
  `PYTHONPATH` and `ANSIBLE_COLLECTIONS_PATHS` to the project-owned bundle.
- Missing, non-executable, hash-mismatched, non-3.12, or out-of-tree Ansible
  bundles return technical failure code 10 with a sanitized diagnostic.
- Runtime installation is never attempted during inspection.
