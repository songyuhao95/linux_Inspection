"""Project-local Python 3.12 and Ansible runtime contract."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
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
    ansible_site_packages: Path
    ansible_module: str = ANSIBLE_MODULE
    ansible_collections_path: Optional[Path] = None

    def ansible_playbook_argv(self, args: Sequence[str]) -> list[str]:
        """Build Ansible argv through this interpreter, never through PATH."""
        return [str(self.python_path), "-m", self.ansible_module, *map(str, args)]

    def ansible_environment(self, base_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        """Return a child environment that imports only the bundled Ansible package."""
        env = dict(os.environ if base_env is None else base_env)
        # Do not inherit a caller's Python installation or Ansible configuration.
        for name in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONUSERBASE",
            "VIRTUAL_ENV",
            "ANSIBLE_CONFIG",
            "ANSIBLE_HOME",
            "ANSIBLE_LIBRARY",
            "ANSIBLE_MODULE_UTILS",
            "ANSIBLE_LOOKUP_PLUGINS",
            "ANSIBLE_FILTER_PLUGINS",
            "ANSIBLE_ACTION_PLUGINS",
            "ANSIBLE_CALLBACK_PLUGINS",
            "ANSIBLE_COLLECTIONS_PATHS",
        ):
            env.pop(name, None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(self.ansible_site_packages)
        if self.ansible_collections_path is not None:
            env["ANSIBLE_COLLECTIONS_PATHS"] = str(self.ansible_collections_path)
        return env


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


def _probe_ansible(
    python_path: Path, site_packages: Path, runtime_root: Path
) -> Path:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(site_packages),
    }
    code = (
        "import ansible, ansible.cli.playbook; "
        "print(ansible.__file__)"
    )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", code],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeContractError("bundled Ansible import probe failed") from exc
    if completed.returncode != 0:
        raise RuntimeContractError(
            "bundled Ansible is missing or its ansible.cli.playbook entry point is unavailable"
        )
    raw_path = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    if not raw_path:
        raise RuntimeContractError("bundled Ansible import probe returned no package path")
    ansible_path = Path(raw_path).resolve()
    try:
        ansible_path.relative_to(site_packages.resolve())
    except ValueError as exc:
        raise RuntimeContractError(
            "Ansible resolved outside the project runtime; system Ansible is forbidden"
        ) from exc
    try:
        ansible_path.relative_to(runtime_root.resolve())
    except ValueError as exc:
        raise RuntimeContractError("bundled Ansible path escapes runtime directory") from exc
    return ansible_path


def _verify_hash(path: Path, expected: Any) -> None:
    if expected in (None, ""):
        return
    if not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeContractError("runtime manifest Python sha256 is invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest.lower() != expected.lower():
        raise RuntimeContractError("project Python sha256 does not match manifest")


def _bundle_files(root: Path) -> list[Path]:
    """Return stable bundle files, excluding interpreter-generated bytecode."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def _verify_bundle_hash(root: Path, expected: Any) -> None:
    """Verify the deterministic hash of the bundled Ansible tree."""
    if expected in (None, ""):
        return
    if not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeContractError("runtime manifest Ansible bundle sha256 is invalid")
    digest = hashlib.sha256()
    for path in _bundle_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if digest.hexdigest().lower() != expected.lower():
        raise RuntimeContractError("bundled Ansible sha256 does not match manifest")


def resolve_runtime(root: Optional[Path] = None) -> RuntimeInfo:
    """Validate and return the project-local Python and bundled Ansible runtime."""
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

    ansible_meta = manifest.get("ansible")
    if not isinstance(ansible_meta, dict):
        raise RuntimeContractError("runtime manifest is missing bundled Ansible metadata")
    ansible_module = str(ansible_meta.get("module", ""))
    if ansible_module != ANSIBLE_MODULE:
        raise RuntimeContractError("runtime manifest Ansible module is unsupported")
    ansible_site_packages = _safe_relative(
        runtime_root, ansible_meta.get("site_packages"), "ansible.site_packages"
    )
    if not ansible_site_packages.is_dir():
        raise RuntimeContractError(
            "bundled Ansible site-packages are missing; system Ansible fallback is forbidden"
        )
    if not (ansible_site_packages / "ansible" / "__init__.py").is_file():
        raise RuntimeContractError("bundled Ansible package is missing")
    if not (ansible_site_packages / "ansible" / "cli" / "playbook.py").is_file():
        raise RuntimeContractError("bundled Ansible playbook entry point is missing")

    collections_value = ansible_meta.get("collections_path")
    collections_path = None
    if collections_value not in (None, ""):
        collections_path = _safe_relative(runtime_root, collections_value, "ansible.collections_path")
        if not collections_path.is_dir():
            raise RuntimeContractError("bundled Ansible collections directory is missing")
    _verify_bundle_hash(runtime_root / "ansible", ansible_meta.get("bundle_sha256"))
    _probe_ansible(python_path, ansible_site_packages, runtime_root)
    return RuntimeInfo(
        runtime_root.resolve(),
        python_path.resolve(),
        version,
        manifest,
        ansible_site_packages.resolve(),
        ansible_module,
        collections_path.resolve() if collections_path is not None else None,
    )


def is_fixture_mode(env: Optional[Mapping[str, str]] = None) -> bool:
    values = os.environ if env is None else env
    return bool(values.get("INSPECT_FIXTURE_DIR", "").strip())


def current_python_for_non_real() -> str:
    """Return the project interpreter path for fixture/query compatibility."""
    name = "python3.12.exe" if os.name == "nt" else "python3.12"
    return str(DEFAULT_RUNTIME_ROOT / "bin" / name)


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
