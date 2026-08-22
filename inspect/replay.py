"""Safe replay-command selection for reports and host-result facts.

A host-result ``evidence.command`` is the collector's implementation command.
It may contain profile placeholders or shell syntax and is therefore not a
copy/paste contract.  ``evidence.replay_command`` is an optional, separately
validated command intended for human reproduction.  This module is deliberately
stdlib-only so collection, normalization, and both renderers can share the
same fail-closed policy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Optional

# Keep this wording stable: it is shown in both report formats when a fact does
# not carry a safe command.  The phrase explicitly tells the operator that the
# value is not a command to execute.
REPLAY_FALLBACK = "不可复制（未提供安全的复现命令）"
REPLAY_COMMAND_FALLBACK = REPLAY_FALLBACK


class ReplayCommandError(ValueError):
    """Raised when a supplied replay command is not safe to publish."""


# Shell control syntax is rejected rather than parsed.  A replay command is a
# single, concrete invocation, not a shell program.
_SHELL_OPERATOR_RE = re.compile(r"(?:&&|\|\||[;&|<>`$()])")
_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{?[^{}\r\n]+\}?\}|<[^>\r\n]+>)"
)
_SYNTAX_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:if|then|else|elif|fi|for|in|do|done|while|until|"
    r"case|esac|function)(?![A-Za-z0-9_])"
)
_FUNCTION_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:function\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)"
)
_URL_USERINFO_RE = re.compile(r"(?i)https?://[^/@\s]+@")
_AUTHORIZATION_RE = re.compile(r"(?i)\bauthorization\b")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:^|[\s'\"])(?:(?:--?|)(?:password|passwd|pwd|secret|token|api[-_]?key|"
    r"access[-_]?key|private[-_]?key|username|user|login)|"
    r"(?:-p|-P|-u|-U)\s+|"
    r"(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key|"
    r"private[-_]?key|authorization)\s*(?:[:=]|\s))"
)


def _has_control_character(value: str) -> bool:
    """Return true for C0/C1/control-format characters.

    Tabs are intentionally rejected too: a report value must be one physical
    line and allowing invisible separators makes review and copy/paste unsafe.
    """
    return any(
        ord(char) in {0x2028, 0x2029}
        or (ord(char) < 32 or 127 <= ord(char) <= 159)
        or unicodedata.category(char) in {"Cc", "Cf"}
        for char in value
    )


def _invalid_reason(value: str) -> Optional[str]:
    if _has_control_character(value):
        return "命令包含控制字符或换行"
    if _SHELL_OPERATOR_RE.search(value):
        return "命令包含 shell 变量、替换或连接器"
    if _PLACEHOLDER_RE.search(value):
        return "命令包含未解析的 profile 占位符"
    if _SYNTAX_WORD_RE.search(value) or _FUNCTION_RE.search(value):
        return "命令包含 shell 条件、循环或函数语法"
    if _URL_USERINFO_RE.search(value):
        return "命令包含 URL 用户信息"
    if _AUTHORIZATION_RE.search(value) or _CREDENTIAL_RE.search(value):
        return "命令包含凭据或 Authorization 信息"
    # A command must contain some non-whitespace text.  This check is kept
    # here as well as in validate_replay_command so callers using this helper
    # cannot accidentally accept an empty value.
    if not value.strip():
        return "命令不能为空"
    return None


def validate_replay_command(
    value: Any, *, allow_none: bool = True
) -> Optional[str]:
    """Validate and return a normalized replay command.

    ``None`` means the optional field was deliberately left unset.  Any
    supplied non-string, empty, multiline, shell-program-like, placeholder,
    or credential-bearing value raises :class:`ReplayCommandError`.
    """
    if value is None:
        if allow_none:
            return None
        raise ReplayCommandError("replay_command 必须为非空单行字符串")
    if not isinstance(value, str):
        raise ReplayCommandError("replay_command 必须为字符串或 null")
    command = value.strip()
    reason = _invalid_reason(command)
    if reason is not None:
        raise ReplayCommandError(f"replay_command 不安全: {reason}")
    return command


def is_safe_replay_command(value: Any) -> bool:
    """Return whether ``value`` is a concrete, publishable command."""
    try:
        validate_replay_command(value, allow_none=False)
    except (ReplayCommandError, TypeError, ValueError):
        return False
    return True


def normalize_replay_command(value: Any) -> Optional[str]:
    """Fail closed: retain only a valid command, otherwise return ``None``.

    Normalization callers use this function when an upstream result explicitly
    supplies a replay command.  It never substitutes ``evidence.command``.
    """
    try:
        return validate_replay_command(value)
    except ReplayCommandError:
        return None


def replay_command_from_evidence(evidence: Any) -> Optional[str]:
    """Read only the optional ``replay_command`` evidence field safely."""
    if not isinstance(evidence, Mapping):
        return None
    return normalize_replay_command(evidence.get("replay_command"))


def select_replay_command(value: Any) -> str:
    """Return the safe replay command or the stable non-command fallback.

    ``value`` may be an evidence mapping or a complete metric mapping.  The
    implementation intentionally never reads a mapping's ``command`` key.
    """
    evidence = value
    if isinstance(value, Mapping) and "evidence" in value:
        evidence = value.get("evidence")
    command = replay_command_from_evidence(evidence)
    return command if command is not None else REPLAY_FALLBACK


def replay_command_or_fallback(value: Any) -> str:
    """Compatibility spelling for :func:`select_replay_command`."""
    return select_replay_command(value)


def safe_replay_command(value: Any) -> Optional[str]:
    """Compatibility spelling for :func:`normalize_replay_command`."""
    return normalize_replay_command(value)


__all__ = [
    "REPLAY_COMMAND_FALLBACK",
    "REPLAY_FALLBACK",
    "ReplayCommandError",
    "is_safe_replay_command",
    "normalize_replay_command",
    "replay_command_from_evidence",
    "replay_command_or_fallback",
    "safe_replay_command",
    "select_replay_command",
    "validate_replay_command",
]
