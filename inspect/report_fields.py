"""Shared, fact-only formatting for report metric fields.

The report layers must explain a recorded result, not evaluate thresholds again.
This module formats the values already present in a host-result-v1 metric and
its optional evidence details.  Both Excel and HTML call the same function so
a fact cannot acquire different threshold prose depending on output format.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, List, Optional

from . import metrics


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
    return str(value).replace("\r", " ").replace("\n", " ")


def _append(parts: List[str], label: str, value: Any) -> None:
    """Append a labelled field, retaining the label for empty facts."""
    parts.append(f"{label}：{_text(value)}")


def _mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping value or an empty read-only view."""
    return value if isinstance(value, Mapping) else {}


def _first_value(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present, non-empty fact from *mapping*."""
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if value is not None and _text(value) != "":
            return value
    return None


def _measurement_object(
    metric: Mapping[str, Any], detail: Mapping[str, Any]
) -> Any:
    """Build one measurement-object value from already recorded context."""
    subject = _first_value(
        detail,
        ("measurement", "measurement_object", "object", "target", "name"),
    )
    if subject is None:
        subject = _first_value(metric, ("name", "metric_id"))

    context: List[str] = []
    for key, label in (
        ("filesystem", "文件系统"),
        ("mount", "挂载点"),
        ("window", "测量周期"),
        ("cpu_cores", "CPU核数"),
        ("interface", "网卡"),
        ("device", "设备"),
        ("path", "路径"),
    ):
        value = detail.get(key)
        if value is not None and _text(value) != "":
            context.append(f"{label}={_text(value)}")

    subject_text = _text(subject)
    if context:
        context_text = "；".join(context)
        return f"{subject_text}（{context_text}）" if subject_text else context_text
    return subject


def _approved_impact(
    metric: Mapping[str, Any],
    detail: Mapping[str, Any],
    threshold: Mapping[str, Any],
) -> Any:
    """Read impact text only from notes or explicitly nested metadata.

    ``metric['impact']`` is intentionally not a host-result-v1 field and is
    never consulted.  The nested metadata spellings are accepted only as
    already-present facts; this helper does not add them to the schema.
    """
    notes = threshold.get("notes")
    if notes is not None and _text(notes) != "":
        return notes

    metadata_sources = [
        threshold.get("metadata"),
        detail.get("metadata"),
        metric.get("metadata"),
        _mapping(metric.get("provenance")).get("metadata"),
    ]
    for metadata in metadata_sources:
        metadata_map = _mapping(metadata)
        value = _first_value(
            metadata_map,
            (
                "impact",
                "impact_description",
                "effect",
                "作用影响",
                "指标作用影响",
            ),
        )
        if value is not None:
            return value

    # provenance.notes is an approved, closed-schema note and is the
    # compatibility fallback for older facts that stored the explanation there.
    provenance_notes = _mapping(metric.get("provenance")).get("notes")
    return provenance_notes


def _status(metric: Mapping[str, Any], detail: Mapping[str, Any]) -> Any:
    """Read a declared status; never derive one from values or thresholds."""
    # The metric status is the fact-source declaration.  Keep it verbatim when
    # present, including UNKNOWN and an explicitly empty value; a detail row is
    # only a fallback for legacy facts that have no metric-level status.
    if "status" in metric:
        return metric.get("status")
    return detail.get("status")


def _catalog_doc_baseline(metric: Mapping[str, Any]) -> Any:
    """Return the approved normative baseline for a registered metric.

    ``normalized_value`` is an observation and must not be presented as the
    documented norm.  Unknown metrics deliberately render an empty value rather
    than borrowing an observed value or a collector threshold.
    """
    metric_id = metric.get("metric_id")
    if not isinstance(metric_id, str):
        return None
    definition = metrics.get_metric(metric_id)
    if not isinstance(definition, Mapping):
        return None
    baseline = definition.get("doc_baseline")
    return baseline if baseline is not None and _text(baseline) != "" else None


def format_threshold_rule(
    metric: Mapping[str, Any], detail: Optional[Mapping[str, Any]] = None
) -> str:
    """Format exactly six declarative sections from recorded facts.

    ``raw_value`` and ``normalized_value`` are never compared here.  The
    catalog's documented baseline is displayed under ``规范值``, while the
    recorded threshold rule is displayed verbatim under ``判定规则``.
    Audit fields such as rule IDs, provenance, and errors remain outside this
    projection.  Every label is emitted, including when its value is empty.
    """
    metric_map = metric if isinstance(metric, Mapping) else {}
    detail_map = detail if isinstance(detail, Mapping) else {}
    threshold = _mapping(metric_map.get("threshold"))

    normative_baseline = _catalog_doc_baseline(metric_map)
    unit = detail_map.get("unit", metric_map.get("unit"))
    threshold_rule = threshold.get("value")
    declared_status = _status(metric_map, detail_map)
    impact = _approved_impact(metric_map, detail_map, threshold)

    parts: List[str] = []
    _append(parts, "测量对象", _measurement_object(metric_map, detail_map))
    _append(parts, "规范值", normative_baseline)
    _append(parts, "单位", unit)
    _append(parts, "判定规则", threshold_rule)
    _append(parts, "声明状态", declared_status)
    _append(parts, "指标作用影响", impact)
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
