"""Project-local Python 3.12 runtime contract.

The repository intentionally does not contain a platform binary. A verified,
offline runtime archive is materialized by ``tools/build-runtime.sh``. Real
execution must use the resulting interpreter; fixture/query execution may use
the caller's interpreter because it never invokes Ansible or a target host.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

EXPECTED_MAJOR = 3
EXPECTED_MINOR = 12
MANIFEST_NAME = "manifest.json"
DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parent.parent / "runtime"
ANSIBLE_MODULE = "ansible.cli.playbook"


class RuntimeContractError(Exception):
    """A missing, invalid, or incompatible project runtime (exit code 10)."""

    exit_code = 10
    category = "dedicated_python_unavailable"


class RuntimeVersionError(RuntimeContractError):
    category = "dedicated_python_version_mismatch"


@dataclass(frozen=True)
class RuntimeInfo:
    root: Path
    python_path: Path
    version: str
    manifest: Mapping[str, Any]

    def ansible_playbook_argv(self, args: Sequence[str]) -> list[str]:
        """Build Ansible argv through this interpreter, never through PATH."""
        return [str(self.python_path), "-m", ANSIBLE_MODULE, *map(str, args)]


def _safe_relative(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise RuntimeContractError(f"runtime manifest {field} must be a relative path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeContractError(f"runtime manifest {field} escapes runtime directory") from exc
    return candidate


def _read_manifest(root: Path) -> Dict[str, Any]:
    path = root / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeContractError(f"runtime manifest is missing or invalid: {path.name}") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RuntimeContractError("runtime manifest schema is unsupported")
    return data


def _validate_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2 or parts[0] != str(EXPECTED_MAJOR) or parts[1] != str(EXPECTED_MINOR):
        raise RuntimeVersionError(
            f"project Python version mismatch: expected {EXPECTED_MAJOR}.{EXPECTED_MINOR}.x; "
            f"got {version or '<unknown>'}"
        )
    return version


def _probe_version(python_path: Path) -> str:
    try:
        completed = subprocess.run(
            [str(python_path), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeContractError("project Python is not executable") from exc
    if completed.returncode != 0:
        raise RuntimeContractError("project Python version probe failed")
    version = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    return _validate_version(version)


def _verify_hash(path: Path, expected: Any) -> None:
    if expected in (None, ""):
        return
    if not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeContractError("runtime manifest Python sha256 is invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest.lower() != expected.lower():
        raise RuntimeContractError("project Python sha256 does not match manifest")


def resolve_runtime(root: Optional[Path] = None) -> RuntimeInfo:
    """Validate and return the project-local Python 3.12 runtime."""
    runtime_root = Path(root) if root is not None else DEFAULT_RUNTIME_ROOT
    manifest = _read_manifest(runtime_root)
    python_meta = manifest.get("python")
    if not isinstance(python_meta, dict):
        raise RuntimeContractError("runtime manifest is missing python metadata")
    python_path = _safe_relative(runtime_root, python_meta.get("path"), "python.path")
    if not python_path.is_file():
        raise RuntimeContractError(
            f"project Python is missing: {python_meta.get('path', '<unset>')}; "
            "system Python fallback is forbidden"
        )
    if os.name != "nt" and not os.access(str(python_path), os.X_OK):
        raise RuntimeContractError("project Python is not executable; system Python fallback is forbidden")
    _verify_hash(python_path, python_meta.get("sha256"))
    version = _validate_version(_probe_version(python_path))
    declared = str(python_meta.get("version", "3.12.x"))
    if not declared.startswith("3.12"):
        raise RuntimeContractError("runtime manifest declares a Python version other than 3.12.x")
    return RuntimeInfo(runtime_root.resolve(), python_path.resolve(), version, manifest)


def is_fixture_mode(env: Optional[Mapping[str, str]] = None) -> bool:
    values = os.environ if env is None else env
    return bool(values.get("INSPECT_FIXTURE_DIR", "").strip())


def current_python_for_non_real() -> str:
    """Return the current interpreter only for fixture/query execution."""
    return sys.executable


__all__ = [
    "ANSIBLE_MODULE",
    "DEFAULT_RUNTIME_ROOT",
    "EXPECTED_MAJOR",
    "EXPECTED_MINOR",
    "RuntimeContractError",
    "RuntimeInfo",
    "RuntimeVersionError",
    "current_python_for_non_real",
    "is_fixture_mode",
    "resolve_runtime",
]
