# Project-local Ansible bundle

This directory is populated only by `tools/build-runtime.sh` from an approved
offline runtime archive. It is intentionally not a package-manager workspace.

The archive must contain:

```text
ansible/
  site-packages/
    ansible/__init__.py
    ansible/cli/playbook.py
  collections/
```

`ansible-core` metadata must be importable by the bundled
`runtime/bin/python3.12`. The runtime resolver checks the exact module
`ansible.cli.playbook` and rejects imports that resolve outside this project
runtime. Real inspection execution therefore cannot silently use a system
Ansible installation.

Do not run `pip install`, `ansible-galaxy`, or a network installer as part of
inspection. Update the approved offline archive and its review evidence
instead, then materialize it with the build script.
