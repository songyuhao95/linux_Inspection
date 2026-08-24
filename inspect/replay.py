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


def manual_command_for_report(metric: Any) -> str:
    """Return the redacted source command for the report ``command`` column.

    This is intentionally separate from ``select_replay_command``: the report
    documents which manual command produced a fact, while replay remains a
    fail-closed, copy/paste-safe convenience.  Implementation placeholders are
    converted to human labels and never reveal credentials.
    """
    metric_id = metric.get("metric_id") if isinstance(metric, Mapping) else metric
    try:
        from inspect import metrics as catalog
        definition = catalog.get_metric(str(metric_id))
    except (ImportError, AttributeError):
        definition = None
    command = definition.get("command") if isinstance(definition, Mapping) else None
    if not isinstance(command, str) or not command.strip():
        return REPLAY_FALLBACK
    replacements = {
        "{nginx_bin}": "<可执行文件>", "{nginx_conf}": "<配置文件>",
        "{nginx_error_log}": "<日志文件>", "{nginx_access_log}": "<日志文件>",
        "{nginx_port}": "<端口>", "{nginx_listener_host}": "<主机>",
        "{keepalived_bin}": "<可执行文件>", "{keepalived_conf}": "<配置文件>",
        "{keepalived_log}": "<日志文件>", "{keepalived_vip}": "<VIP>",
        "{keepalived_port}": "<端口>", "{timeout}": "<超时秒数>",
        "{elasticsearch_listener_host}": "<主机>", "{elasticsearch_http_port}": "<端口>",
        "{elasticsearch_auth}": "<认证参数>", "{elasticsearch_cert}": "<证书路径>",
    }
    for source, replacement in replacements.items():
        command = command.replace(source, replacement)
    # Do not publish implementation placeholders or credential-bearing values.
    command = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "<参数>", command)
    command = command.replace("CHANGE_ME", "<密码>")
    return command.strip()

# This is a public, versioned projection catalog.  It contains only concrete
# commands that are safe to show to an operator; collector templates remain in
# metrics.py and are never copied here.  Metrics without an approved mapping
# intentionally use REPLAY_FALLBACK.
REPLAY_CATALOG_VERSION = "replay-v1"
REPLAY_CATALOG = {
    "local.nginx.config.valid": "nginx -t -c <配置文件>",
    "local.port.listening": "ss -tlnp",
}


class ReplayCommandError(ValueError):
    """Raised when a supplied replay command is not safe to publish."""


# Shell control syntax is rejected rather than parsed.  A replay command is a
# single, concrete invocation, not a shell program.
_SHELL_OPERATOR_RE = re.compile(r"(?:&&|\|\||[;&|<>`$()])")
_PLACEHOLDER_RE = re.compile(
    r"(?:\{\{?[^{}\r\n]+\}?\}|<[^>\r\n]+>)"
)
_HUMAN_PLACEHOLDER_RE = re.compile(r"<(?:路径|配置文件|账户|密码)>")
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


def _command_code(value: str) -> str:
    """Return executable text, excluding a trailing human shell comment."""
    quote: Optional[str] = None
    escaped = False
    for index, char in enumerate(value):
        if quote is not None:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = None
            escaped = False
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#":
            return value[:index].rstrip()
    return value


def _invalid_reason(value: str) -> Optional[str]:
    code = _command_code(value)
    if _has_control_character(value):
        return "命令包含控制字符或换行"

    # Human replacement markers are the only permitted angle-bracket text.
    # Remove them before checking redirection syntax, but reject every other
    # unresolved implementation placeholder.
    unapproved = _PLACEHOLDER_RE.search(
        _HUMAN_PLACEHOLDER_RE.sub("PLACEHOLDER", code)
    )
    if unapproved:
        return "命令包含未解析的 profile 占位符"
    safe_code = _HUMAN_PLACEHOLDER_RE.sub("PLACEHOLDER", code)
    if _SHELL_OPERATOR_RE.search(safe_code):
        return "命令包含 shell 变量、替换或连接器"
    if _SYNTAX_WORD_RE.search(code) or _FUNCTION_RE.search(code):
        return "命令包含 shell 条件、循环或函数语法"
    if _URL_USERINFO_RE.search(value):
        return "命令包含 URL 用户信息"
    if _AUTHORIZATION_RE.search(value) or _CREDENTIAL_RE.search(value):
        return "命令包含凭据或 Authorization 信息"
    # A command must contain some non-whitespace text.  This check is kept
    # here as well as in validate_replay_command so callers using this helper
    # cannot accidentally accept an empty value.
    if not code.strip():
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
    implementation intentionally never publishes a mapping's ordinary
    ``command`` key.  A complete metric may use the static catalog only when
    its evidence does not contain collector-only ``command`` text.
    """
    evidence = value
    metric_id = None
    if isinstance(value, Mapping) and "evidence" in value:
        metric_id = value.get("metric_id")
        evidence = value.get("evidence")
    command = replay_command_from_evidence(evidence)
    if command is not None:
        return command
    if metric_id is not None and (
        not isinstance(evidence, Mapping) or "command" not in evidence
    ):
        return build_replay_command(metric_id)
    return REPLAY_FALLBACK


def build_replay_command(metric_id: Any) -> str:
    """Build a safe public replay command from a registered metric ID.

    The lookup is deliberately independent of collector evidence.  A missing
    or invalid catalog entry is stable and fail-closed, so an ordinary
    ``evidence.command`` can never become a public replay command.
    """
    if not isinstance(metric_id, str):
        return REPLAY_FALLBACK
    command = REPLAY_CATALOG.get(metric_id)
    if command is None:
        return REPLAY_FALLBACK
    return normalize_replay_command(command) or REPLAY_FALLBACK


def replay_command_or_fallback(value: Any) -> str:
    """Compatibility spelling for :func:`select_replay_command`."""
    return select_replay_command(value)


def safe_replay_command(value: Any) -> Optional[str]:
    """Compatibility spelling for :func:`normalize_replay_command`."""
    return normalize_replay_command(value)


__all__ = [
    "REPLAY_COMMAND_FALLBACK",
    "REPLAY_CATALOG",
    "REPLAY_CATALOG_VERSION",
    "REPLAY_FALLBACK",
    "ReplayCommandError",
    "manual_command_for_report",
    "is_safe_replay_command",
    "normalize_replay_command",
    "build_replay_command",
    "replay_command_from_evidence",
    "replay_command_or_fallback",
    "safe_replay_command",
    "select_replay_command",
    "validate_replay_command",
]
