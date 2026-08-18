"""inspect/render_stdout.py — stdout 终端渲染（T-105）。

职责（docs/specs/reporting-roadmap.md §2/§5、host-result-v1.md §8、
technical-design.md §8，RR §2 stdout 行）：
  - 只读消费 host-result-v1 JSON（RR §1 数据流：采集 → normalize → 原子写
    JSON → 报表）；绝不二次采集、不连接主机、不执行命令；
  - 内容与顺序（RR §2）：先全局（run 摘要）后逐主机（主机摘要 →
    失败/未知指标列表）→ 退出码说明；UNKNOWN 与 ERROR 必须显式展示原因
    （missing/conflict/permission/timeout），不得静默过滤（RR §6.2）；
  - 主机摘要：execution_status 徽标（SUCCESS/PARTIAL/ERROR，RR §5 徽标与
    业务状态区分）+ 四状态计数（取自 JSON execution_summary）；
  - execution_status != SUCCESS 时必须展示技术失败计数（executed/failed），
    不得掩盖为业务正常（HR §8）；ERROR 主机无业务结论（AE §6）；
  - 彩色化可选（RR §5：OK 绿 / WARN 黄 / CRIT 红 / UNKNOWN 灰；四状态颜色
    与 HTML 色板 #2E7D32/#F9A825/#C62828/#757575 语义一致，终端用标准
    ANSI 近似）；无颜色环境（NO_COLOR 环境变量 / TERM=dumb / 非 TTY）以
    符号/缩写区分（[OK]/[WARN]/[CRIT]/[UNKN] 徽标、?/! 前缀、[SUCCESS] 等）；
  - 状态计数一律取自 JSON execution_summary（RR §6.1 三类报表计数必须
    一致，展示层不做二次计算）。

模块边界（TD §4）：渲染层只依赖事实源 JSON 读取（fact_source 读路径）；
不导入 config/metrics/ansible_runner/probe/subprocess；状态/错误码常量
与 normalize/ansible_runner 同名同值（均为 HR §2/§3 枚举转写），不引
入采集或归一化逻辑。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO

from inspect import fact_source

# --------------------------------------------------------------------------
# 常量（HR §2 枚举转写；与 normalize.py 同名同值，模块边界内不互导）
# --------------------------------------------------------------------------

# 业务状态（HR §2.2）
STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_CRIT = "CRIT"
STATUS_UNKNOWN = "UNKNOWN"
STATUSES = (STATUS_OK, STATUS_WARN, STATUS_CRIT, STATUS_UNKNOWN)

# 执行状态（HR §2.1）
EXEC_SUCCESS = "SUCCESS"
EXEC_PARTIAL = "PARTIAL"
EXEC_ERROR = "ERROR"
EXEC_STATUSES = (EXEC_SUCCESS, EXEC_PARTIAL, EXEC_ERROR)

# 无颜色环境徽标（RR §2 符号/缩写区分；颜色环境同文本 + ANSI 色）
BADGES = {
    STATUS_OK: "[OK]",
    STATUS_WARN: "[WARN]",
    STATUS_CRIT: "[CRIT]",
    STATUS_UNKNOWN: "[UNKN]",
}
EXEC_BADGES = {
    EXEC_SUCCESS: "[SUCCESS]",
    EXEC_PARTIAL: "[PARTIAL]",
    EXEC_ERROR: "[ERROR]",
}

# ANSI 前景色（RR §5 四状态色板语义：#2E7D32 绿 / #F9A825 黄 / #C62828 红 /
# #757575 灰；终端用标准 ANSI 近似色，HTML 报表使用精确色值）
_ANSI_COLOR = {
    STATUS_OK: "\x1b[32m",
    STATUS_WARN: "\x1b[33m",
    STATUS_CRIT: "\x1b[31m",
    STATUS_UNKNOWN: "\x1b[90m",
    EXEC_SUCCESS: "\x1b[32m",
    EXEC_PARTIAL: "\x1b[33m",
    EXEC_ERROR: "\x1b[31m",
}
_ANSI_BOLD = "\x1b[1m"
_ANSI_RESET = "\x1b[0m"

# error.code → 原因分类（RR §2 四类；其余显式展示 other:<code>，绝不静默）
_ERROR_REASON = {
    "PERMISSION_DENIED": "permission",
    "TIMEOUT": "timeout",
    "COMMAND_NOT_FOUND": "missing",
    "DATA_MISSING": "missing",
}

# 业务 UNKNOWN（无 error）的注记关键词 → 原因（与 config 基线 UNKNOWN
# reason 语义一致；C 编号见 docs/reviews/docx-source-conflicts.md C1-C13）
_CONFLICT_RE = re.compile(r"(?:冲突|conflict|\bC(?:3|8|10)\b)")
_MISSING_RE = re.compile(r"(?:缺失|无配置|未定义|missing|\bC(?:4|5|13)\b)")


# --------------------------------------------------------------------------
# 颜色/徽标
# --------------------------------------------------------------------------


def color_enabled(
    stream: Optional[TextIO] = None,
    *,
    force: Optional[bool] = None,
) -> bool:
    """是否输出 ANSI 颜色。

    NO_COLOR 环境变量（任意值）或 TERM=dumb 或 stream 非 TTY → False；
    force 显式覆盖（测试/调用方决定）。实现遵循 no-color.org 约定。
    """
    if force is not None:
        return bool(force)
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(getattr(stream, "isatty", lambda: False)())
    except Exception:
        return False


def badge(
    status: str,
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """业务状态徽标（RR §5）：无颜色环境 → `[OK]`/`[WARN]`/`[CRIT]`/`[UNKN]`。"""
    text = BADGES.get(status, f"[{status}]")
    if not color_enabled(stream, force=color):
        return text
    return f"{_ANSI_COLOR.get(status, '')}{text}{_ANSI_RESET}"


def execution_badge(
    execution_status: str,
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """execution_status 徽标（RR §5：与业务状态徽标区分，加粗 + 颜色）。"""
    text = EXEC_BADGES.get(execution_status, f"[{execution_status}]")
    if not color_enabled(stream, force=color):
        return text
    return f"{_ANSI_BOLD}{_ANSI_COLOR.get(execution_status, '')}{text}{_ANSI_RESET}"


# --------------------------------------------------------------------------
# UNKNOWN/ERROR 显式原因（RR §2 / HR §8）
# --------------------------------------------------------------------------


def classify_unknown_reason(metric: Mapping[str, Any]) -> str:
    """UNKNOWN/ERROR 指标的原因分类（显式展示，不静默过滤）。

    返回 RR §2 四类之一：missing / conflict / permission / timeout；
    其余 error.code 返回 other:<code>（原始码显式展示）。
    优先级：error.code 映射 > threshold.layer 缺失（→ missing）>
    注记关键词（冲突/缺失；C 编号）> 缺省 missing。
    """
    error = metric.get("error")
    if error and error.get("code"):
        code = str(error["code"])
        return _ERROR_REASON.get(code, f"other:{code.lower()}")
    threshold = metric.get("threshold") or {}
    notes = " ".join(
        str(x or "")
        for x in (
            threshold.get("notes"),
            (metric.get("provenance") or {}).get("notes"),
        )
    )
    if threshold.get("layer") is None:
        return "missing"  # 无规则/无判定依据（缺数据/缺规则）
    if _CONFLICT_RE.search(notes):
        return "conflict"
    if _MISSING_RE.search(notes):
        return "missing"
    return "missing"  # unresolved 层无注记 → 缺规则/数据


def reason_detail(metric: Mapping[str, Any], *, limit: int = 120) -> str:
    """原因明细文本（error.code+message 或 threshold/provenance 注记；截断防刷屏）。

    error 指标显式携带原始错误码（如 `PERMISSION_DENIED: …`），配合
    classify_unknown_reason 的四类原因展示；注记文本去重（threshold 与
    provenance 常为同一句）。
    """
    error = metric.get("error")
    if error and error.get("code"):
        code = str(error["code"])
        msg = str(error.get("message") or "")
        detail = f"{code}: {msg}" if msg else code
        return detail[:limit] + ("…" if len(detail) > limit else "")
    threshold = metric.get("threshold") or {}
    provenance = metric.get("provenance") or {}
    notes: List[str] = []
    for x in (threshold.get("notes"), provenance.get("notes")):
        text = str(x or "").strip()
        if text and text not in notes:
            notes.append(text)
    detail = "；".join(notes)
    return detail[:limit] + ("…" if len(detail) > limit else "")


def _problem_line(
    metric: Mapping[str, Any],
    *,
    color: Optional[bool],
    stream: Optional[TextIO] = None,
) -> str:
    """失败/未知列表单行：符号 + 徽标 + 指标 + 原因（显式）。"""
    symbol = "!" if metric.get("error") else "?"
    b = badge(metric.get("status") or STATUS_UNKNOWN, color=color, stream=stream)
    metric_id = str(metric.get("metric_id") or "-")
    name = str(metric.get("name") or "")
    reason = classify_unknown_reason(metric)
    detail = reason_detail(metric)
    return (
        f"    {symbol} {b} {metric_id:<38} {name:<14}"
        f" 原因={reason}（{detail}）"
    ).rstrip()


# --------------------------------------------------------------------------
# run 聚合（RR §6.1：计数一律取自 JSON execution_summary，不做二次计算）
# --------------------------------------------------------------------------

_SUMMARY_KEYS = ("total_metrics", "ok", "warn", "crit", "unknown", "executed", "failed")


def _aggregate_run(docs: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    agg: Dict[str, int] = {k: 0 for k in _SUMMARY_KEYS}
    for doc in docs:
        summary = doc.get("execution_summary") or {}
        for key in _SUMMARY_KEYS:
            agg[key] += int(summary.get(key, 0) or 0)
    return agg


def _exec_counts(docs: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for doc in docs:
        es = doc.get("execution_status")
        counts[es if es in EXEC_STATUSES else "-"] = (
            counts.get(es if es in EXEC_STATUSES else "-", 0) + 1
        )
    return counts


def _overall_conclusion(docs: Sequence[Mapping[str, Any]]) -> str:
    """整体结论（全部由 JSON 计数推导，不发明结论；HR §8 技术失败优先展示）。"""
    agg = _aggregate_run(docs)
    exec_counts = _exec_counts(docs)
    if exec_counts.get(EXEC_ERROR, 0) > 0:
        return (
            f"存在技术失败（failed={agg['failed']}）且无业务结论主机 "
            f"{exec_counts[EXEC_ERROR]} 台 —— 详见主机摘要与失败/未知列表"
        )
    if agg["failed"] > 0:
        return (
            f"存在技术失败（failed={agg['failed']}）—— 失败计数显式展示不掩盖"
            f"（HR §8），详见失败/未知列表"
        )
    if agg["crit"] > 0:
        return f"存在业务告警 CRIT（{agg['crit']}）—— 结合 --fail-on critical 与退出码说明"
    if agg["unknown"] > 0:
        return f"存在 UNKNOWN（{agg['unknown']}）—— 显式原因见失败/未知列表"
    if agg["warn"] > 0:
        return f"存在 WARN（{agg['warn']}）—— 关注级，建议复核"
    return "全部指标 OK"


# --------------------------------------------------------------------------
# 各段渲染（RR §2 内容与顺序：先全局后逐主机）
# --------------------------------------------------------------------------


def render_run_summary(
    docs: Sequence[Mapping[str, Any]],
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """run 摘要（全局段，RR §2 先全局）。"""
    lines = ["run 摘要"]
    if not docs:
        lines.append("  无主机文档（本次巡检未产生事实源 JSON）")
        return "\n".join(lines)
    first = docs[0]
    agg = _aggregate_run(docs)
    exec_counts = _exec_counts(docs)
    exec_part = " ".join(
        f"{k}={v}" for k, v in sorted(exec_counts.items())
    )
    lines.append(f"  run_id:        {first.get('run_id') or '-'}")
    lines.append(f"  inspection_id: {first.get('inspection_id') or '-'}")
    lines.append(f"  采集时间:       {first.get('collected_at') or '-'}")
    dur = first.get("duration_sec")
    lines.append(f"  时长(sec):     {dur if dur is not None else '-'}")
    lines.append(f"  主机数:        {len(docs)}（{exec_part}）")
    lines.append(
        f"  指标总数:      {agg['total_metrics']}"
        f"（OK={agg['ok']} WARN={agg['warn']} CRIT={agg['crit']} "
        f"UNKNOWN={agg['unknown']}）"
    )
    non_success = [k for k in (EXEC_PARTIAL, EXEC_ERROR) if exec_counts.get(k, 0) > 0]
    exec_line = f"  执行:          executed={agg['executed']} failed={agg['failed']}"
    if non_success:
        exec_line += (
            "（execution_status != SUCCESS：技术失败计数显式展示，HR §8，"
            f"涉及 {', '.join(non_success)}）"
        )
    lines.append(exec_line)
    lines.append(f"  整体结论:      {_overall_conclusion(docs)}")
    return "\n".join(lines)


def render_host_summary(
    doc: Mapping[str, Any],
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """单主机摘要（execution_status 徽标 + 四状态计数，RR §2/§5）。"""
    host = doc.get("host") or {}
    summary = doc.get("execution_summary") or {}
    es = doc.get("execution_status")
    b = execution_badge(es if es in EXEC_STATUSES else "-", color=color, stream=stream)
    name = str(host.get("name") or "-")
    if es == EXEC_ERROR and not doc.get("metrics"):
        # AE §6：主机级 ERROR 不产生业务结论；技术失败计数在 () 中展示（HR §8）
        return (
            f"  {b} {name:<24} 无业务结论"
            f"（executed={summary.get('executed', 0)} failed={summary.get('failed', 0)}）"
        )
    counts = (
        f"OK={summary.get('ok', 0)} WARN={summary.get('warn', 0)} "
        f"CRIT={summary.get('crit', 0)} UNKNOWN={summary.get('unknown', 0)}"
    )
    return (
        f"  {b} {name:<24} {counts}"
        f"（executed={summary.get('executed', 0)} failed={summary.get('failed', 0)}）"
    )


def _metric_display_value(metric: Mapping[str, Any]) -> str:
    """Format the already-normalized JSON value for terminal display."""
    value = metric.get("normalized_value")
    if value is None:
        value = metric.get("raw_value")
    if value is None:
        text = "-"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    unit = str(metric.get("unit") or "").strip()
    return f"{text} {unit}".rstrip()


def render_metric_values(
    doc: Mapping[str, Any],
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """Render executed metric values from one host-result-v1 JSON document.

    The metric name, value and unit all come from the fact source.  Metrics
    with a technical collection error stay in ``render_problem_list`` so the
    value section only contains metrics for which collection produced a value.
    """
    lines = ["  指标结果（从 JSON 事实源读取）"]
    shown = False
    for metric in doc.get("metrics", []):
        if metric.get("error") is not None:
            continue
        shown = True
        status = str(metric.get("status") or STATUS_UNKNOWN)
        name = str(metric.get("name") or metric.get("metric_id") or "-")
        lines.append(
            f"    {badge(status, color=color, stream=stream)} {name}: "
            f"{_metric_display_value(metric)}"
        )
    if not shown:
        lines.append("    （无已执行指标）")
    return "\n".join(lines)


def render_problem_list(
    docs: Sequence[Mapping[str, Any]],
    *,
    host_errors: Optional[Mapping[str, Any]] = None,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """失败/未知指标列表（UNKNOWN/ERROR 显式原因，RR §2/§6.2）。

    - 业务 UNKNOWN（? 前缀）与 error 指标（! 前缀）逐条列出，原因显式
      （missing/conflict/permission/timeout/other:<code>）；
    - ERROR 主机（metrics=[]，AE §6）：注明无业务指标，主机级错误明细
      取自汇总索引 host_errors（事实源 schema 无主机级 error 字段，
      T-104 报告 D1）；
    - 无任何 UNKNOWN/ERROR → 显式输出“（无 UNKNOWN/ERROR 指标）”，
      不得静默消失（RR §6.2）。
    """
    lines = ["失败/未知指标列表（UNKNOWN/ERROR 显式原因，RR §2）"]
    host_errors = host_errors or {}
    shown = False
    for doc in docs:
        host = doc.get("host") or {}
        name = str(host.get("name") or "-")
        es = doc.get("execution_status")
        if es == EXEC_ERROR and not doc.get("metrics"):
            lines.append(f"  {name}:")
            err = host_errors.get(name) if isinstance(host_errors, dict) else None
            detail = ""
            if err:
                code = str(err.get("code") or "")
                msg = str(err.get("message") or "")
                detail = f"（{code}" + (f": {msg}" if msg else "") + "）"
            lines.append(f"    主机级执行失败：无业务指标，技术失败计数见主机摘要{detail}")
            shown = True
            continue
        problems = [
            m for m in doc.get("metrics", []) if m.get("status") == STATUS_UNKNOWN
        ]
        if not problems:
            continue
        shown = True
        lines.append(f"  {name}:")
        for m in problems:
            lines.append(_problem_line(m, color=color, stream=stream))
    if not shown:
        lines.append("  （无 UNKNOWN/ERROR 指标）")
    return "\n".join(lines)


def render_exit_code_note() -> str:
    """退出码说明（cli-contract §4 表逐项转写，RR §2 内容之一）。"""
    return "\n".join(
        [
            "退出码说明（cli-contract §4）",
            "  0   成功（巡检完成；含业务 WARN/CRIT，未启用 --fail-on critical 时）",
            "  2   用法错误（未知选项、参数缺失、互斥选项、不支持的中间件选择）",
            "  10  执行失败（技术：控制端失败、inventory 解析失败、连接失败、"
            "事实源写入失败；与业务状态无关）",
            "  20  业务告警（仅 --fail-on critical 启用且任一指标 status=CRIT）",
        ]
    )


# --------------------------------------------------------------------------
# 整份报告
# --------------------------------------------------------------------------


def render_report(
    docs: Sequence[Mapping[str, Any]],
    *,
    host_errors: Optional[Mapping[str, Any]] = None,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """整份 stdout 报告（RR §2 顺序：run 摘要 → 主机摘要 → 失败/未知列表 → 退出码说明）。

    只读渲染内存中的 host-result-v1 文档（测试/编排直接使用）；不采集。
    """
    parts = [
        "巡检报告（host-result-v1；报表只读消费事实源 JSON，RR §1 不二次采集）",
        render_run_summary(docs, color=color, stream=stream),
        "主机摘要",
    ]
    for doc in docs:
        parts.append(render_host_summary(doc, color=color, stream=stream))
        parts.append(render_metric_values(doc, color=color, stream=stream))
    parts.append(render_problem_list(docs, host_errors=host_errors, color=color, stream=stream))
    parts.append(render_exit_code_note())
    return "\n\n".join(parts)


def render_inspection_report(
    out_dir: Path,
    inspection_id: str,
    *,
    color: Optional[bool] = None,
    stream: Optional[TextIO] = None,
) -> str:
    """从事实源目录渲染整份报告（TD §3 布局，只读消费 JSON）。

    布局：<out_dir>/<inspection_id>/hosts/<host>.json +
    inspection-<inspection_id>-index.json；主机级 ERROR 明细（code/message）
    取自汇总索引（schema 无主机级 error 字段，T-104 报告 D1）。
    损坏/缺失 JSON → fact_source.FactSourceError（调用方映射退出码 10，
    cli-contract §4）；本函数只读，不触发任何采集。
    """
    out_dir = Path(out_dir)
    index = fact_source.read_inspection_index(
        out_dir / inspection_id / f"inspection-{inspection_id}-index.json"
    )
    docs: List[Dict[str, Any]] = []
    host_errors: Dict[str, Any] = {}
    for entry in index.get("hosts", []):
        host_file = entry.get("file")
        path = (
            Path(host_file)
            if host_file
            else out_dir / inspection_id / "hosts" / f"{entry.get('host')}.json"
        )
        doc = fact_source.read_host_result(path)
        docs.append(doc)
        host_errors[doc["host"]["name"]] = entry.get("error")
    return render_report(docs, host_errors=host_errors, color=color, stream=stream)


__all__ = [
    "EXEC_BADGES",
    "EXEC_ERROR",
    "EXEC_PARTIAL",
    "EXEC_STATUSES",
    "EXEC_SUCCESS",
    "STATUS_CRIT",
    "STATUS_OK",
    "STATUS_UNKNOWN",
    "STATUS_WARN",
    "STATUSES",
    "BADGES",
    "badge",
    "classify_unknown_reason",
    "color_enabled",
    "execution_badge",
    "reason_detail",
    "render_exit_code_note",
    "render_host_summary",
    "render_inspection_report",
    "render_metric_values",
    "render_problem_list",
    "render_report",
    "render_run_summary",
]
