"""inspect/render_html.py — 离线单文件 HTML 渲染（T-127）。

职责（RR §4/§5、TD §8 选型、HR §8、REQ-R-05/06/07）：
  - 只读消费 host-result-v1 文档列表（事实源 JSON）→ 单文件 HTML；
  - 全内联零外链：模板 CSS/JS 全内联，无 `<link`/`<script src`/fetch/
    外链资源（AC-2 机械断言见 contract-T-127-v1 ac_map，模板级断言
    tests/test_render_html.py 覆盖模板与最终产物两层）；
  - 数据以 `<script type="application/json">` 内嵌（只读；展示层不做
    二次计算——宏观计数/整体结论/维度列表均在渲染期计算为静态文本，
    浏览器 JS 只做显隐过滤）；
  - 文件名默认 `<inspection-id>.html`（TD §3 布局）；`out_path` 参数
    覆盖（对应 CLI `--html PATH`，函数参数语义，cli-contract §2）；
  - 不可信文本（evidence 命令/日志片段、error.message、threshold
    source_anchor、provenance 备注、主机名等）一律 HTML 转义
    （html.escape quote=True）；内嵌 JSON 中 "</" 转义为 "<\\/" 防止
    `</script>` 越界闭合；全部动态文本的 "$" 双写为 "$$"（模板经
    string.Template 渲染，TD §8：stdlib 零依赖）；
  - 渲染失败（输入损坏/模板缺失/占位符渲染失败/写入失败）→
    RenderHtmlError（exit_code=10，cli-contract §4 执行失败语义）。

模块边界（TD §4）：渲染层只依赖 stdlib（html/json/string/pathlib/datetime）
与事实源 JSON 字节；不导入 metrics/normalize/config/fact_source，不采集、
不连接；文档结构校验为渲染层最小防御（深度校验属上游 fact_source）。

只读性：本模块不修改传入文档；多次渲染可从同一 JSON 重生成
（TD §11 报表可随时重生成）。
"""

from __future__ import annotations

import html
import json
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

# cli-contract §4：渲染失败按执行失败处理
EXIT_RENDER_ERROR = 10

# 模板唯一来源：inspect/templates/html-report-v1.html（TD §8 选型）
DEFAULT_TEMPLATE = Path(__file__).parent / "templates" / "html-report-v1.html"

# RR §5 四业务状态（顺序即导航按钮顺序）
STATUSES: Sequence[str] = ("OK", "WARN", "CRIT", "UNKNOWN")
EXECUTION_STATUSES: Sequence[str] = ("SUCCESS", "PARTIAL", "ERROR")

# execution_summary 键（host-result-v1 §2）→ 业务状态
SUMMARY_KEYS: Mapping[str, str] = {
    "OK": "ok",
    "WARN": "warn",
    "CRIT": "crit",
    "UNKNOWN": "unknown",
}

# 逐指标卡片字段标签（RR §4：threshold/evidence/error/provenance）
_THRESHOLD_FIELDS: Sequence[tuple] = (
    ("阈值", "layer"),
    ("阈值", "rule_id"),
    ("阈值", "value"),
    ("阈值", "source_anchor"),
    ("阈值", "notes"),
)
_EVIDENCE_FIELDS: Sequence[tuple] = (
    ("证据", "command"),
    ("证据", "output_summary"),
    ("证据", "raw_ref"),
    ("证据", "sampled_at"),
)
_ERROR_FIELDS: Sequence[tuple] = (
    ("错误", "code"),
    ("错误", "message"),
)
_PROVENANCE_FIELDS: Sequence[tuple] = (
    ("来源", "config_sources"),
    ("来源", "doc_sources"),
    ("来源", "notes"),
)


class RenderHtmlError(Exception):
    """HTML 渲染失败（调用方映射退出码 10，cli-contract §4）。"""

    def __init__(self, message: str, *, exit_code: int = EXIT_RENDER_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


def esc(value: Any) -> str:
    """HTML 转义（不可信文本一律经此输出）。

    html.escape(quote=True)：`& < > " '` 全部转义（正文与属性双安全）。
    注意：页面经 string.Template 渲染，但映射值原样插入（不参与模板
    语法解析），因此值内的 "$" 无需也**不可**转义（转义会显示为 "$$"）。
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _fmt(value: Any) -> str:
    """展示文本（**原始文本**，不转义；调用方统一 esc 输出）。

    None → 空；list/tuple → 分号连接；dict → key=value 分号连接。
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(_fmt(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(
            str(k) + "=" + _fmt(v) for k, v in value.items()
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _value_or_dash(value: Any) -> str:
    """字段值 HTML：None → 灰色占位 —；否则 esc(_fmt(value))。"""
    if value is None:
        return '<span class="field-null">—</span>'
    return esc(_fmt(value))


def _embed_json(docs: Sequence[Mapping[str, Any]]) -> str:
    """内嵌 JSON 文本（只读展示数据，TD §8）。

    安全防御："</" 序列内的反斜杠转义为 "<\\/"（文档注释中写作
    反斜杠+斜杠）：字符串值内的 `</script>` 不得提前闭合内嵌脚本标签
    （json 合法转义，浏览器解析后原样恢复）。映射值经 string.Template
    原样插入，数据内美元符号无需处理。
    """
    text = json.dumps(list(docs), ensure_ascii=False, indent=1)
    text = text.replace("</", "<\\/")
    return text


def _host_counts(doc: Mapping[str, Any]) -> Dict[str, int]:
    """主机四状态计数（宏观卡片）。

    优先使用事实源自带 execution_summary（RR §1 以 JSON 为准，展示层
    不二次计算）；summary 缺失（防御路径）时回退按 metrics 重算。
    """
    summary = doc.get("execution_summary")
    counts = {"OK": 0, "WARN": 0, "CRIT": 0, "UNKNOWN": 0}
    if isinstance(summary, Mapping):
        for st, key in SUMMARY_KEYS.items():
            counts[st] = _int_of(summary.get(key))
        return counts
    for m in doc.get("metrics") or []:
        st = m.get("status")
        if st in counts:
            counts[st] += 1
    return counts


def _conclusion(counts: Mapping[str, int], execution_status: str, failed: int) -> str:
    """主机整体结论（渲染期静态文本，RR §4 宏观卡片）。"""
    parts: List[str] = []
    if execution_status != "SUCCESS":
        parts.append(
            "执行状态 " + esc(execution_status) + "，存在技术失败 "
            + str(failed) + " 项（错误详情见指标卡片）"
        )
    if counts["CRIT"]:
        parts.append("存在 CRIT 告警 " + str(counts["CRIT"]) + " 项，请尽快处理")
    elif counts["WARN"]:
        parts.append("存在 WARN 关注项 " + str(counts["WARN"]) + " 项，建议跟进")
    elif counts["UNKNOWN"]:
        parts.append("存在 UNKNOWN " + str(counts["UNKNOWN"]) + " 项，需人工确认")
    elif execution_status == "SUCCESS":
        parts.append("全部指标正常")
    return "整体结论：" + "；".join(parts) + "。"


def _badge(execution_status: str) -> str:
    """execution_status 徽标（RR §5：描边徽标，区别于业务状态填充徽标）。"""
    es = execution_status if execution_status in EXECUTION_STATUSES else "UNKNOWN"
    cls = "exec-" + es.lower()
    return (
        '<span class="exec-badge ' + cls + '">' + esc(es) + "</span>"
    )


def _chip(status: str) -> str:
    """业务状态填充徽标（RR §5 色板）。"""
    st = status if status in STATUSES else "UNKNOWN"
    return (
        '<span class="chip chip-' + st.lower() + '">' + esc(st) + "</span>"
    )


def _field_rows(section: str, obj: Any, fields: Sequence[tuple]) -> str:
    """指标卡片字段行（label + key 双语，机械可断言；RR §4 字段全集）。"""
    obj = obj if isinstance(obj, Mapping) else {}
    rows: List[str] = []
    for label, key in fields:
        value = obj.get(key)
        if value is None:
            rows.append(
                '<tr><th scope="row">' + esc(label) + " " + esc(key)
                + '</th><td><span class="field-null">—</span></td></tr>'
            )
        else:
            rows.append(
                '<tr><th scope="row">' + esc(label) + " " + esc(key)
                + "</th><td>" + esc(_fmt(value)) + "</td></tr>"
            )
    return "".join(rows)


def _as_strings(value: Any) -> List[str]:
    """将 profile/middleware 字段规范为去重后的字符串列表。"""
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: List[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _middleware_values(doc: Mapping[str, Any], metric: Mapping[str, Any]) -> List[str]:
    """为指标确定展示/筛选用的中间件维度，不改变事实源。"""
    for key in ("middleware", "middleware_id", "module_id", "module"):
        values = _as_strings(metric.get(key))
        if values:
            return values
    host = doc.get("host") or {}
    values = _as_strings(host.get("product_profiles"))
    return values or ["Linux 基础"]


def _metric_card(
    metric: Mapping[str, Any],
    host_name: str,
    middleware_values: Optional[Sequence[str]] = None,
    *,
    show_host: bool = False,
) -> str:
    """单指标卡片；show_host 用于跨主机的状态/中间件分组视图。"""
    status = metric.get("status")
    if status not in STATUSES:
        status = "UNKNOWN"
    metric_id = metric.get("metric_id", "")
    name = metric.get("name", "")
    middleware_values = list(middleware_values or ["Linux 基础"])
    middleware_attr = "|".join(middleware_values)
    card_cls = "metric-card status-" + status.lower()
    context = (
        '<span class="card-context">主机：' + esc(host_name) + "</span>"
        if show_host else ""
    )
    parts: List[str] = [
        '<div class="' + card_cls + '" data-status="' + esc(status)
        + '" data-host="' + esc(host_name)
        + '" data-metric-id="' + esc(metric_id)
        + '" data-middleware="' + esc(middleware_attr) + '">',
        '<div class="card-head"><h4 class="card-title">'
        '<span class="metric-id">' + esc(metric_id) + "</span>"
        '<span class="metric-name">' + esc(name) + "</span>"
        + context + _chip(status) + "</h4></div>",
        '<dl class="card-values">',
        '<div><dt>raw_value</dt><dd>' + _value_or_dash(metric.get("raw_value")) + "</dd></div>",
        '<div><dt>normalized_value</dt><dd>'
        + _value_or_dash(metric.get("normalized_value"))
        + "</dd></div>",
        '<div><dt>unit</dt><dd>' + _value_or_dash(metric.get("unit")) + "</dd></div>",
        "</dl>",
        '<table class="card-fields">'
        + _field_rows("阈值", metric.get("threshold"), _THRESHOLD_FIELDS)
        + "</table>",
        '<details class="card-details"><summary>证据与来源锚点</summary>',
        '<table class="card-fields">'
        + _field_rows("证据", metric.get("evidence"), _EVIDENCE_FIELDS)
        + _field_rows("错误", metric.get("error"), _ERROR_FIELDS)
        + _field_rows("来源", metric.get("provenance"), _PROVENANCE_FIELDS)
        + "</table></details>",
        "</div>",
    ]
    return "".join(parts)


def _int_of(value: Any, default: int = 0) -> int:
    """安全取整（execution_summary 数值为 int，防御非数值输入）。"""
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _summary_of(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    """execution_summary（非 Mapping 输入防御）。"""
    s = doc.get("execution_summary")
    return s if isinstance(s, Mapping) else {}


def _macro_card(doc: Mapping[str, Any]) -> str:
    """宏观卡片：主机名 + execution_status 徽标 + 四状态计数 + 整体结论。"""
    host = doc.get("host") or {}
    host_name = host.get("name", "")
    execution_status = doc.get("execution_status", "UNKNOWN")
    counts = _host_counts(doc)
    summary = _summary_of(doc)
    failed = _int_of(summary.get("failed"))
    total = counts["OK"] + counts["WARN"] + counts["CRIT"] + counts["UNKNOWN"]
    total_metrics = _int_of(summary.get("total_metrics"), default=total)
    executed = _int_of(summary.get("executed"), default=total_metrics)
    parts: List[str] = [
        '<section class="macro-card" data-host="' + esc(host_name) + '">',
        '<h3 class="macro-host">' + esc(host_name) + " " + _badge(execution_status) + "</h3>",
        '<ul class="macro-counts">',
    ]
    for st in STATUSES:
        parts.append(
            '<li class="count count-' + st.lower() + '">' + esc(st)
            + "<b>" + str(counts[st]) + "</b></li>"
        )
    parts.append("</ul>")
    parts.append(
        '<p class="macro-conclusion">' + _conclusion(counts, execution_status, failed) + "</p>"
    )
    parts.append(
        '<p class="macro-meta">执行状态：' + esc(execution_status)
        + " · 指标总数 " + str(total_metrics) + " · 已执行 " + str(executed)
        + " · 技术失败 " + str(failed) + "</p>"
    )
    parts.append("</section>")
    return "".join(parts)


def _host_section(doc: Mapping[str, Any]) -> str:
    """按主机分组的详情区：标题/徽标/元信息 + 逐指标卡片。"""
    host = doc.get("host") or {}
    host_name = host.get("name", "")
    execution_status = doc.get("execution_status", "UNKNOWN")
    summary = _summary_of(doc)
    failed = _int_of(summary.get("failed"))
    meta = (
        "IP：" + esc(host.get("ip", ""))
        + " · inventory_source：" + esc(host.get("inventory_source", ""))
        + " · product_profiles：" + esc(_fmt(host.get("product_profiles") or []))
        + " · collected_at：" + esc(doc.get("collected_at", ""))
        + " · duration_sec：" + esc(doc.get("duration_sec", ""))
        + " · 技术失败：" + str(failed)
    )
    cards = [
        _metric_card(m, host_name, _middleware_values(doc, m))
        for m in doc.get("metrics") or []
    ]
    return "".join([
        '<section class="report-group host-section" data-host="' + esc(host_name)
        + '" id="host-' + esc(host_name) + '">',
        '<h2 class="host-title">' + esc(host_name) + " " + _badge(execution_status) + "</h2>",
        '<p class="host-meta">' + meta + "</p>",
        "".join(cards),
        "</section>",
    ])


def _run_totals(docs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """run 级汇总（渲染期聚合事实源 execution_summary 数值）。"""
    totals: Dict[str, int] = {
        "total_metrics": 0, "ok": 0, "warn": 0, "crit": 0,
        "unknown": 0, "executed": 0, "failed": 0,
    }
    exec_dist: Dict[str, int] = {"SUCCESS": 0, "PARTIAL": 0, "ERROR": 0}
    for doc in docs:
        summary = _summary_of(doc)
        for key in totals:
            totals[key] += _int_of(summary.get(key))
        es = doc.get("execution_status")
        if es in exec_dist:
            exec_dist[es] += 1
    totals["hosts"] = len(docs)
    totals["exec_dist"] = exec_dist
    return totals


def _run_conclusion(docs: Sequence[Mapping[str, Any]], totals: Mapping[str, Any]) -> str:
    """run 级整体结论（渲染期静态文本）。"""
    exec_dist = totals["exec_dist"]
    host_parts = [
        "%d 台 %s" % (exec_dist[es], es)
        for es in EXECUTION_STATUSES
        if exec_dist[es]
    ]
    parts = ["主机 %d（%s）" % (len(docs), "，".join(host_parts) or "无")]
    if totals["crit"]:
        parts.append("CRIT 指标 %d 项" % totals["crit"])
    if totals["warn"]:
        parts.append("WARN 指标 %d 项" % totals["warn"])
    if totals["unknown"]:
        parts.append("UNKNOWN 指标 %d 项（需人工确认）" % totals["unknown"])
    if totals["failed"]:
        parts.append("技术失败 %d 项（见各指标卡错误详情）" % totals["failed"])
    if not totals["crit"] and not totals["warn"] and not totals["unknown"] and not totals["failed"]:
        parts.append("全部指标正常")
    return "整体结论：" + "；".join(parts) + "。"


def _middleware_dimensions(docs: Sequence[Mapping[str, Any]]) -> List[str]:
    """中间件维度：优先使用 metric/host product_profiles，空时归入 Linux 基础。"""
    result: List[str] = []
    for doc in docs:
        for metric in doc.get("metrics") or []:
            for value in _middleware_values(doc, metric):
                if value not in result:
                    result.append(value)
    return result


def _run_summary_nav(docs, totals, inspection_id, run_id, collected_at, generated_at) -> str:
    """正文顶部 Run 摘要块（保留旧函数名以兼容调用方）。"""
    exec_dist = totals["exec_dist"]
    dist_text = " · ".join(
        "%d %s" % (exec_dist[es], es) for es in EXECUTION_STATUSES if exec_dist[es]
    ) or "—"
    items = [
        ("run_id", run_id),
        ("inspection_id", inspection_id),
        ("主机数", str(len(docs))),
        ("指标总数", str(totals["total_metrics"])),
        ("OK / WARN / CRIT / UNKNOWN", "%d / %d / %d / %d"
         % (totals["ok"], totals["warn"], totals["crit"], totals["unknown"])),
        ("技术失败（failed）", str(totals["failed"])),
        ("执行状态分布", dist_text),
        ("采集时间", collected_at),
        ("生成时间", generated_at),
    ]
    rows = "".join(
        "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>" for k, v in items
    )
    return (
        '<header class="run-header" aria-label="Run 摘要">'
        '<h1>巡检 HTML 报表 — ' + esc(inspection_id) + "</h1>"
        '<p class="run-stream">' + _run_conclusion(docs, totals) + "</p>"
        '<dl class="run-meta">' + rows + "</dl>"
        "</header>"
    )


def _multi_select_filter(kind: str, title: str, options: Sequence[tuple]) -> str:
    """左侧隐藏下拉多选：原生 details + 搜索框 + checkbox。"""
    option_rows: List[str] = []
    for value, label in options:
        option_rows.append(
            '<label class="filter-option"><input type="checkbox" class="filter-check" '
            'data-filter-kind="' + esc(kind) + '" data-filter-value="' + esc(value) + '">'
            '<span>' + esc(label) + "</span></label>"
        )
    return (
        '<details class="multi-select" data-filter-kind="' + esc(kind) + '">'
        '<summary>' + esc(title) + '<span class="selection-count">未选择</span></summary>'
        '<div class="multi-menu">'
        '<input type="search" class="filter-search" data-search-kind="' + esc(kind)
        + '" placeholder="搜索' + esc(title) + '" aria-label="搜索' + esc(title) + '">'
        '<div class="filter-options">' + "".join(option_rows) + "</div>"
        "</div></details>"
    )


def _host_nav(docs: Sequence[Mapping[str, Any]]) -> str:
    """左导航主机多选筛选器。"""
    options = []
    for doc in docs:
        host = doc.get("host") or {}
        name = str(host.get("name", ""))
        options.append((name, name))
    return _multi_select_filter("host", "主机列表", options)


def _status_filters() -> str:
    """左导航状态多选筛选器。"""
    return _multi_select_filter("status", "状态筛选", [(st, st) for st in STATUSES])


def _middleware_nav(docs: Sequence[Mapping[str, Any]]) -> str:
    """左导航中间件多选筛选器。"""
    values = _middleware_dimensions(docs)
    return _multi_select_filter("middleware", "中间件", [(value, value) for value in values])


def _macro_cards(docs: Sequence[Mapping[str, Any]]) -> str:
    return "".join(_macro_card(doc) for doc in docs)


def _status_details(docs: Sequence[Mapping[str, Any]]) -> str:
    parts: List[str] = []
    for status in STATUSES:
        cards: List[str] = []
        for doc in docs:
            host_name = str((doc.get("host") or {}).get("name", ""))
            for metric in doc.get("metrics") or []:
                metric_status = metric.get("status") if metric.get("status") in STATUSES else "UNKNOWN"
                if metric_status == status:
                    cards.append(_metric_card(
                        metric, host_name, _middleware_values(doc, metric), show_host=True
                    ))
        if cards:
            parts.append(
                '<section class="report-group status-group" data-group-value="' + esc(status) + '">'
                '<h2 class="group-title">状态：' + _chip(status) + '</h2>'
                + "".join(cards) + "</section>"
            )
    return "".join(parts)


def _middleware_details(docs: Sequence[Mapping[str, Any]]) -> str:
    parts: List[str] = []
    for middleware in _middleware_dimensions(docs):
        cards: List[str] = []
        for doc in docs:
            host_name = str((doc.get("host") or {}).get("name", ""))
            for metric in doc.get("metrics") or []:
                values = _middleware_values(doc, metric)
                if middleware in values:
                    cards.append(_metric_card(metric, host_name, values, show_host=True))
        if cards:
            parts.append(
                '<section class="report-group middleware-group" data-group-value="' + esc(middleware) + '">'
                '<h2 class="group-title">中间件：' + esc(middleware) + "</h2>"
                + "".join(cards) + "</section>"
            )
    return "".join(parts)


def _grouped_details(docs: Sequence[Mapping[str, Any]]) -> str:
    """预渲染三种分组视图，浏览器端只切换显隐。"""
    return (
        '<div class="group-view active" id="group-view-host" data-group-mode="host">'
        + "".join(_host_section(doc) for doc in docs)
        + "</div>"
        '<div class="group-view" id="group-view-status" data-group-mode="status">'
        + _status_details(docs)
        + "</div>"
        '<div class="group-view" id="group-view-middleware" data-group-mode="middleware">'
        + _middleware_details(docs)
        + "</div>"
    )

def render_html(
    docs: Sequence[Mapping[str, Any]],
    *,
    out_path: Optional[Union[str, Path]] = None,
    template: Optional[Union[str, Path]] = None,
) -> Path:
    """渲染入口：host-result-v1 文档列表 → 离线单文件 HTML。

    参数（函数参数语义，对应 CLI `--html [PATH]`，cli-contract §2）：
      - docs：只读消费的 host-result-v1 文档列表（同一 inspection_id）；
      - out_path：输出文件路径；缺省 `<inspection_id>.html`（当前目录，
        TD §3 布局 `<inspection-id>.html`）；提供时覆盖默认文件名；
      - template：模板文件路径；缺省 `inspect/templates/html-report-v1.html`。

    返回实际写入的 Path。失败 → RenderHtmlError（exit_code=10）。
    本函数不修改 docs（多次渲染可重生成，TD §11）。
    """
    docs = list(docs)
    if not docs:
        raise RenderHtmlError("没有可渲染的主机文档（docs 为空）")
    for idx, doc in enumerate(docs):
        if not isinstance(doc, Mapping):
            raise RenderHtmlError("docs[%d] 不是对象（host-result-v1 文档）" % idx)

    inspection_ids = {doc.get("inspection_id") for doc in docs}
    if len(inspection_ids) != 1:
        raise RenderHtmlError(
            "同一份 HTML 只能承载一个 inspection_id（事实源一致性，"
            "host-result-v1 §5）：%s" % "、".join(str(v) for v in sorted(inspection_ids))
        )
    inspection_id = docs[0].get("inspection_id")
    if not inspection_id or not isinstance(inspection_id, str):
        raise RenderHtmlError("inspection_id 缺失或非法: %r" % (inspection_id,))
    run_id = docs[0].get("run_id")
    if not isinstance(run_id, str):
        run_id = ""

    tpl_path = Path(template) if template is not None else DEFAULT_TEMPLATE
    try:
        tpl_text = tpl_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RenderHtmlError("模板读取失败: %s（%s）" % (tpl_path, exc))

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    totals = _run_totals(docs)
    collected_at = docs[0].get("collected_at", "")

    mapping = {
        "TITLE": "%s — 巡检 HTML 报表" % inspection_id,
        "RUN_SUMMARY": _run_summary_nav(
            docs, totals, inspection_id, run_id, collected_at, generated_at
        ),
        "HOST_NAV": _host_nav(docs),
        "STATUS_FILTERS": _status_filters(),
        "MIDDLEWARE_NAV": _middleware_nav(docs),
        "MACRO_CARDS": _macro_cards(docs),
        "GROUPED_DETAILS": _grouped_details(docs),
        "DATA_JSON": _embed_json(docs),
        "GENERATED_AT": esc(generated_at),
    }

    try:
        html_text = string.Template(tpl_text).substitute(mapping)
    except ValueError as exc:
        raise RenderHtmlError("模板占位符渲染失败: %s" % exc)

    if out_path is None:
        out_path = Path(inspection_id + ".html")
    out = Path(out_path)
    parent = out.parent
    if str(parent) not in ("", "."):
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderHtmlError("HTML 输出目录创建失败: %s（%s）" % (parent, exc))
    try:
        out.write_text(html_text, encoding="utf-8")
    except OSError as exc:
        raise RenderHtmlError("HTML 写入失败: %s（%s）" % (out, exc))
    return out


def render_html_from_files(
    paths: Sequence[Union[str, Path]],
    *,
    out_path: Optional[Union[str, Path]] = None,
    template: Optional[Union[str, Path]] = None,
) -> Path:
    """按事实源文件渲染：每个文件为单个 host-result-v1 文档
    （HR §5 布局 `<out>/<inspection_id>/hosts/<host>.json`）。

    文件缺失/非法 JSON/非对象 → RenderHtmlError（exit_code=10）；
    深度 schema 校验属上游 fact_source.read_host_result，本层保持
    stdlib 零依赖（TD §4 渲染层只依赖 JSON 读取）。
    """
    docs: List[Dict[str, Any]] = []
    for p in paths:
        path = Path(p)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RenderHtmlError("事实源读取失败: %s（%s）" % (path, exc))
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise RenderHtmlError("事实源损坏（JSON 解析失败）: %s（%s）" % (path, exc))
        if not isinstance(doc, Mapping):
            raise RenderHtmlError("事实源不是 host-result-v1 文档: %s" % path)
        docs.append(dict(doc))
    return render_html(docs, out_path=out_path, template=template)


__all__ = [
    "DEFAULT_TEMPLATE",
    "EXECUTION_STATUSES",
    "EXIT_RENDER_ERROR",
    "RenderHtmlError",
    "STATUSES",
    "esc",
    "render_html",
    "render_html_from_files",
]
