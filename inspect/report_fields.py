"""Shared, fact-only formatting for report metric fields.

The report layers must explain a recorded result, not evaluate thresholds again.
This module formats the values already present in a host-result-v1 metric and
its optional evidence details.  Both Excel and HTML call the same function so
a fact cannot acquire different threshold prose depending on output format.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List, Optional


_MISSING = object()


def _text(value: Any) -> str:
    """Convert a fact field to readable text without evaluating it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return "、".join(_text(item) for item in value)
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}={_text(item)}" for key, item in value.items()
        )
    return str(value)


def _append(parts: List[str], label: str, value: Any) -> None:
    """Append a labelled field only when the fact actually supplies it."""
    text = _text(value)
    if text != "":
        parts.append(f"{label}：{text}")


def _status(metric: Mapping[str, Any], detail: Optional[Mapping[str, Any]]) -> Any:
    """Read a declared status; never derive one from values or thresholds."""
    metric_status = metric.get("status")
    # A top-level UNKNOWN is an explicit fact-source declaration.  Do not let
    # an expanded detail row make it look like the renderer recomputed a
    # business status.
    if metric_status == "UNKNOWN":
        return metric_status
    if isinstance(detail, Mapping) and "status" in detail:
        return detail.get("status")
    return metric_status


def _detail_context(detail: Optional[Mapping[str, Any]]) -> List[str]:
    if not isinstance(detail, Mapping):
        return []
    parts: List[str] = []
    for key, label in (
        ("window", "测量周期"),
        ("cpu_cores", "CPU核数"),
        ("mount", "挂载点"),
        ("filesystem", "文件系统"),
    ):
        _append(parts, label, detail.get(key))
    return parts


def format_threshold_rule(
    metric: Mapping[str, Any], detail: Optional[Mapping[str, Any]] = None
) -> str:
    """Format a detailed threshold explanation from fact fields only.

    Included fields are deliberately declarative: detail context, raw and
    normalized values/unit, threshold metadata, declared status, impact,
    provenance, and error.  No numeric comparison, status inference, or
    threshold lookup occurs here.  Newlines make long explanations naturally
    pre-wrappable in HTML and wrap-friendly in Excel.
    """
    metric = metric if isinstance(metric, Mapping) else {}
    threshold = metric.get("threshold")
    threshold = threshold if isinstance(threshold, Mapping) else {}
    provenance = metric.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else provenance
    error = metric.get("error")

    parts: List[str] = _detail_context(detail)
    if not parts:
        _append(parts, "测量对象", metric.get("name") or metric.get("metric_id") or "指标")

    # Detail values, when explicitly present, describe that expanded fact row.
    # Otherwise use the metric-level fields exactly as declared by the source.
    detail_map = detail if isinstance(detail, Mapping) else {}
    raw = detail_map.get("raw_value", metric.get("raw_value"))
    normalized = detail_map.get("normalized_value", metric.get("normalized_value"))
    _append(parts, "原始值", raw)
    _append(parts, "规范值", normalized)
    _append(parts, "单位", metric.get("unit"))

    # Include every supplied threshold fact field, rather than choosing a
    # preferred rule representation or rebuilding a rule from the value.
    threshold_value = threshold.get("value")
    if threshold_value is not None and str(threshold_value) != "":
        # Keep the historical label while retaining the source value verbatim
        # (the symbol replacement is presentation-only, never a comparison).
        display_value = str(threshold_value).replace(">=", "≥").replace("<=", "≤")
        parts.append(f"判定规则：{display_value}")
    elif threshold.get("notes") is not None and str(threshold.get("notes")) != "":
        parts.append(f"判定说明：{threshold.get('notes')}")
    elif threshold.get("layer") is not None and str(threshold.get("layer")) != "":
        parts.append(f"判定层：{threshold.get('layer')}")
    else:
        parts.append("判定规则：事实源未提供")
    _append(parts, "规则标识", threshold.get("rule_id"))
    _append(parts, "阈值层", threshold.get("layer"))
    _append(parts, "来源锚点", threshold.get("source_anchor"))
    # When notes already served as the historical 判定说明, still expose the
    # explicit threshold metadata label for the detailed report contract.
    _append(parts, "阈值说明", threshold.get("notes"))

    declared_status = _status(metric, detail)
    _append(parts, "声明状态", declared_status)
    _append(parts, "影响", metric.get("impact"))
    _append(parts, "溯源", provenance)

    if error is not None:
        _append(parts, "技术错误", error)

    # UNKNOWN is a fact-source declaration.  Explain why it remains UNKNOWN,
    # but do not infer a different status from raw/normalized values.
    if declared_status == "UNKNOWN":
        if error is not None:
            parts.append("说明：技术失败，保留事实源声明 UNKNOWN，未重新判定")
        else:
            parts.append("说明：数据不足或阈值规则未解析，保留事实源声明 UNKNOWN，未重新判定")

    return "；\n".join(parts)


def threshold_rule_text(
    metric: Mapping[str, Any], detail: Optional[Mapping[str, Any]] = None
) -> str:
    """Compatibility spelling for :func:`format_threshold_rule`."""
    return format_threshold_rule(metric, detail)


def format_report_fields(
    metric: Mapping[str, Any], detail: Optional[Mapping[str, Any]] = None
) -> str:
    """Compatibility spelling used by older report integrations."""
    return format_threshold_rule(metric, detail)


__all__ = [
    "format_report_fields",
    "format_threshold_rule",
    "threshold_rule_text",
]
