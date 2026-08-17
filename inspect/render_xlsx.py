"""inspect/render_xlsx.py — Excel 报表渲染（T-106，xlsxwriter，三 Sheet）。

职责（docs/specs/reporting-roadmap.md §3/§5、technical-design.md §4/§8、
host-result-v1.md §8，REQ-R-03/04/07/08）：
  - 只读消费 host-result-v1 JSON（版本化 JSON 唯一事实源，RR §1/§6）：
    不采集、不连接、不写事实源；报表只读 JSON，可随时重生成（TD §11
    回滚）；本模块不导入 inspect 包内其他模块（禁止反向依赖与环，TD §4）。
  - 三 Sheet 布局（RR §3 表格）：
      Overview         run 信息、主机×状态汇总、状态计数、阈值版本
                       （linux-common-p0-v1）、生成时间；
      Local            每主机每指标一行：metric_id / raw_value /
                       normalized_value / unit / status / threshold 规则 /
                       来源锚点 / evidence 摘要 / provenance；
      Errors-Evidence  所有 error 非空的指标与主机：error.code / message /
                       command / output_summary；以及文档冲突/缺失导致的
                       UNKNOWN 清单。
  - 四状态文字+背景色（RR §5）：OK #2E7D32 / WARN #F9A825 /
    CRIT #C62828 / UNKNOWN #757575；CRIT 值红色字体（用户需求：达到
    告警阈值的值红色字体）；UNKNOWN 独立计数、不混入 OK 计数；
    execution_status（SUCCESS/PARTIAL/ERROR）以徽标样式区分于业务状态。
  - 文件名 `<inspection-id>.xlsx`；out_path（`--xlsx-out` 语义）可覆盖
    （函数参数语义，CLI 接线由集成阶段完成）。
  - xlsxwriter 为 requirements.txt 已声明运行时依赖但本任务不安装：
    import 缺失 → RendererError（exit_code=10，cli-contract §4 执行失败
    语义，TD §8 失败处理"明确报错、不静默跳过"）。xlsxwriter 惰性导入，
    模块在缺失环境下仍可导入（模块级常量/结构契约可断言，合同要求）。

模块边界（TD §4 渲染层行）：只依赖 stdlib（json/pathlib/datetime）与
事实源 JSON；不导入 config/metrics/ansible_runner/normalize/fact_source；
不执行任何命令、不访问网络/目标主机。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

# cli-contract §4：渲染失败（技术）按执行失败处理
EXIT_RENDER_ERROR = 10

# RR §5 四状态色板（G1 已确认；颜色可配置留待后续版本）
COLOR_OK = "#2E7D32"        # 正常
COLOR_WARN = "#F9A825"      # 关注
COLOR_CRIT = "#C62828"      # 告警/故障
COLOR_UNKNOWN = "#757575"   # 无规则/冲突/权限/缺失

STATUS_COLORS: Dict[str, str] = {
    "OK": COLOR_OK,
    "WARN": COLOR_WARN,
    "CRIT": COLOR_CRIT,
    "UNKNOWN": COLOR_UNKNOWN,
}
VALID_STATUSES = tuple(STATUS_COLORS)

# RR §3 三 Sheet
SHEET_OVERVIEW = "Overview"
SHEET_LOCAL = "Local"
SHEET_ERRORS = "Errors-Evidence"
SHEET_NAMES = (SHEET_OVERVIEW, SHEET_LOCAL, SHEET_ERRORS)

# RR §3 Local 列（每主机每指标一行）：host 标识主机（多主机汇总），
# name 为指标中文名；其余列与 RR 表格逐项对应
LOCAL_HEADERS = (
    "host", "metric_id", "name", "raw_value", "normalized_value", "unit",
    "status", "threshold_rule", "source_anchor", "evidence_summary",
    "provenance",
)

# RR §3 Errors-Evidence 列：error.code/message/command/output_summary；
# UNKNOWN（文档冲突/缺失）清单行 error_code 为空，note 注明原因
ERRORS_HEADERS = (
    "host", "metric_id", "name", "status", "error_code", "message",
    "command", "output_summary", "note",
)

# host-result-v1 顶层必填键（host-result-v1.md §2 / technical-design §7.1）
_TOP_LEVEL_KEYS = (
    "schema", "schema_version", "run_id", "inspection_id", "host",
    "collected_at", "duration_sec", "execution_status", "execution_summary",
    "metrics", "meta",
)
# metric 必填键（host-result-v1.md §3.1 必填列；error 可选）
_METRIC_KEYS = (
    "metric_id", "name", "scope", "status", "raw_value", "unit",
    "threshold", "evidence", "provenance",
)
_THRESHOLD_KEYS = ("layer", "rule_id", "value", "source_anchor")
_EVIDENCE_KEYS = ("command", "output_summary", "sampled_at")
_PROVENANCE_KEYS = ("config_sources", "doc_sources")


class RendererError(Exception):
    """Excel 渲染失败（xlsxwriter 缺失/文档损坏/结构不完整/写入失败）。

    语义对应 cli-contract §4 退出码 10（执行失败）：调用方映射
    `exit_code` 到进程退出码；不静默跳过（TD §8 失败处理）。
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_RENDER_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def count_statuses(doc: Mapping[str, Any]) -> Dict[str, int]:
    """按 metrics 数组统计业务四状态（UNKNOWN 独立计数，不混入 OK）。

    - 合法输入下结果与 doc["execution_summary"] 的 ok/warn/crit/unknown
      一致（RR §6 一致性要求 1）；非法 status → RendererError（不伪装）。
    """
    counts = {"OK": 0, "WARN": 0, "CRIT": 0, "UNKNOWN": 0}
    for metric in doc["metrics"]:
        status = metric.get("status")
        if status not in counts:
            raise RendererError(
                f"指标状态非法（应为 {list(VALID_STATUSES)}）: {status!r}"
            )
        counts[status] += 1
    return counts


def _require_dict(value: Any, what: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise RendererError(f"事实源结构不完整: {what} 不是对象（{type(value).__name__}）")
    return value


def _require_keys(obj: Mapping[str, Any], keys: Sequence[str], what: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise RendererError(
            f"事实源结构不完整: {what} 缺少必填键 {missing}"
        )


def validate_doc(doc: Mapping[str, Any]) -> None:
    """host-result-v1 文档结构校验（损坏检测：不完整/非法 → RendererError）。

    - 顶层必填键（HR §2）、host.name、execution_summary 计数、
      metric 必填键与 status 枚举（HR §3.1）、threshold/evidence/
      provenance 子对象、error 形状（HR §3.2）；
    - 状态计数一致性：count_statuses 结果必须与 execution_summary
      ok/warn/crit/unknown 一致（RR §6；不一致即事实源损坏，明确报错
      而非静默呈现错误计数）。
    """
    _require_dict(doc, "顶层文档")
    _require_keys(doc, _TOP_LEVEL_KEYS, "顶层文档")
    if doc["schema"] != "host-result-v1":
        raise RendererError(
            f"事实源 schema 不识别（期望 host-result-v1）: {doc['schema']!r}"
        )
    if not isinstance(doc.get("schema_version"), int) or doc["schema_version"] < 1:
        raise RendererError(
            f"事实源 schema_version 非法: {doc.get('schema_version')!r}"
        )
    host = _require_dict(doc["host"], "host")
    if not isinstance(host.get("name"), str) or not host["name"]:
        raise RendererError("事实源结构不完整: host.name 必须为非空字符串")
    summary = _require_dict(doc["execution_summary"], "execution_summary")
    for key in ("ok", "warn", "crit", "unknown"):
        if not isinstance(summary.get(key), int) or summary[key] < 0:
            raise RendererError(
                f"事实源结构不完整: execution_summary.{key} 必须为非负整数"
            )
    if not isinstance(doc["metrics"], list):
        raise RendererError("事实源结构不完整: metrics 必须为数组")
    for metric in doc["metrics"]:
        _require_keys(metric, _METRIC_KEYS, "metric")
        if metric["status"] not in VALID_STATUSES:
            raise RendererError(
                f"指标状态非法（应为 {list(VALID_STATUSES)}）: "
                f"{metric['metric_id']} → {metric['status']!r}"
            )
        threshold = _require_dict(metric["threshold"], "metric.threshold")
        _require_keys(threshold, _THRESHOLD_KEYS, "metric.threshold")
        evidence = _require_dict(metric["evidence"], "metric.evidence")
        _require_keys(evidence, _EVIDENCE_KEYS, "metric.evidence")
        provenance = _require_dict(metric["provenance"], "metric.provenance")
        _require_keys(provenance, _PROVENANCE_KEYS, "metric.provenance")
        error = metric.get("error")
        if error is not None:
            error = _require_dict(error, "metric.error")
            _require_keys(error, ("code", "message", "metric_status"), "metric.error")
            if error.get("metric_status") != "UNKNOWN":
                raise RendererError(
                    f"error 存在时业务 status 必须为 UNKNOWN（HR §3.2）: "
                    f"{metric['metric_id']}"
                )
            if metric["status"] != "UNKNOWN":
                raise RendererError(
                    f"error 存在时业务 status 必须为 UNKNOWN（HR §3.2）: "
                    f"{metric['metric_id']} → {metric['status']!r}"
                )
    # 状态计数一致性（RR §6）：UNKNOWN 独立计数，不混入 OK
    computed = count_statuses(doc)
    for status in VALID_STATUSES:
        if summary[status.lower()] != computed[status]:
            raise RendererError(
                f"事实源状态计数不一致（UNKNOWN 独立计数）: "
                f"execution_summary.{status.lower()}={summary[status.lower()]} "
                f"≠ metrics 统计 {computed[status]}（host={host['name']}）"
            )


def _collect_threshold_versions(docs: Sequence[Mapping[str, Any]]) -> List[str]:
    """阈值版本集合（RR §3 Overview"阈值版本（linux-common-p0-v1）"）。

    取 threshold.rule_id 的版本前缀（`<version>.<metric>.<status>` 首段，
    如 linux-common-p0-v1）；规则缺失（全部 UNKNOWN）时回退 metric.scope，
    避免空值；保持稳定排序输出。
    """
    versions: set = set()
    for doc in docs:
        for metric in doc["metrics"]:
            rule_id = (metric.get("threshold") or {}).get("rule_id")
            if isinstance(rule_id, str) and "." in rule_id:
                versions.add(rule_id.split(".", 1)[0])
    if not versions:
        for doc in docs:
            for metric in doc["metrics"]:
                if isinstance(metric.get("scope"), str) and metric["scope"]:
                    versions.add(metric["scope"])
    return sorted(versions)


def _require_xlsxwriter():
    """惰性导入 xlsxwriter；缺失 → RendererError（exit_code=10 语义）。"""
    try:
        import xlsxwriter  # noqa: PLC0415 — 惰性导入（模块在缺失环境可导入）
    except ImportError as exc:
        raise RendererError(
            "xlsxwriter 未安装，无法生成 Excel（requirements.txt 已声明；"
            "请先安装该依赖后重试）"
        ) from exc
    return xlsxwriter


def _write_workbook(
    docs: Sequence[Mapping[str, Any]], target: Path
) -> None:
    xlsxwriter = _require_xlsxwriter()
    try:
        workbook = xlsxwriter.Workbook(str(target))
    except OSError as exc:
        raise RendererError(f"Excel 文件创建失败: {target}（{exc}）") from exc

    # ---- 样式（RR §5 色板；execution_status 徽标与业务状态区分） ----
    title_fmt = workbook.add_format({"bold": True, "font_size": 14})
    section_fmt = workbook.add_format({"bold": True})
    header_fmt = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#37474F",
         "border": 1, "text_wrap": True, "valign": "vcenter"}
    )
    cell_fmt = workbook.add_format({"border": 1})
    note_fmt = workbook.add_format({"italic": True, "font_color": "#616161"})
    # 业务四状态：文字 + 背景色（RR §5）
    status_fmts: Dict[str, Any] = {
        status: workbook.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": STATUS_COLORS[status],
             "border": 1}
        )
        for status in VALID_STATUSES
    }
    # execution_status 徽标：深色文字 + 浅灰底，明显区别于四业务状态彩色
    exec_badge_fmt = workbook.add_format(
        {"bold": True, "font_color": "#37474F", "bg_color": "#ECEFF1", "border": 1}
    )
    # CRIT 值红色字体（用户需求：达到告警阈值的值红色字体）
    crit_value_fmt = workbook.add_format(
        {"font_color": COLOR_CRIT, "border": 1}
    )

    first = docs[0]
    inspection_id = first["inspection_id"]

    # ================= Overview（RR §3：run 信息/主机×状态汇总/状态计数/
    # 阈值版本/生成时间） =================
    ws = workbook.add_worksheet(SHEET_OVERVIEW)
    ws.set_column(0, 0, 26)
    ws.set_column(1, 7, 14)
    ws.write(0, 0, f"巡检报表 {inspection_id}", title_fmt)

    row = 2
    run_info: List[tuple] = [
        ("run_id", first["run_id"]),
        ("inspection_id", inspection_id),
        ("host", ", ".join(doc["host"]["name"] for doc in docs)),
        ("collected_at", first["collected_at"]),
        ("duration_sec", first["duration_sec"]),
        ("execution_status", first["execution_status"]),
        ("阈值版本", " / ".join(_collect_threshold_versions(docs))),
        ("生成时间", _iso_now()),
    ]
    for label, value in run_info:
        ws.write(row, 0, label, section_fmt)
        ws.write(row, 1, value)
        row += 1

    # 主机×状态汇总（逐主机：四业务状态计数 + 执行状态徽标）
    row += 1
    ws.write(row, 0, "主机×状态汇总", section_fmt)
    row += 1
    summary_headers = (
        "host", "execution_status", "OK", "WARN", "CRIT", "UNKNOWN",
        "executed", "failed",
    )
    for col, header in enumerate(summary_headers):
        ws.write(row, col, header, header_fmt)
    row += 1
    for doc in docs:
        counts = count_statuses(doc)
        summary = doc["execution_summary"]
        ws.write(row, 0, doc["host"]["name"], cell_fmt)
        ws.write(row, 1, doc["execution_status"], exec_badge_fmt)
        for col, status in enumerate(VALID_STATUSES):
            ws.write(row, col + 2, counts[status], status_fmts[status])
        ws.write(row, 6, summary["executed"], cell_fmt)
        ws.write(row, 7, summary["failed"], cell_fmt)
        row += 1

    # 状态计数（合计）：UNKNOWN 独立列，不混入 OK
    row += 1
    ws.write(row, 0, "状态计数（合计）", section_fmt)
    row += 1
    for col, header in enumerate(("OK", "WARN", "CRIT", "UNKNOWN", "合计")):
        ws.write(row, col, header, header_fmt)
    row += 1
    total = {"OK": 0, "WARN": 0, "CRIT": 0, "UNKNOWN": 0}
    for doc in docs:
        counts = count_statuses(doc)
        for status in VALID_STATUSES:
            total[status] += counts[status]
    for col, status in enumerate(VALID_STATUSES):
        ws.write(row, col, total[status], status_fmts[status])
    ws.write(row, 4, sum(total.values()), cell_fmt)
    row += 1
    ws.write(
        row, 0,
        "注：UNKNOWN 独立计数，不混入 OK；状态颜色见 RR §5 "
        "（OK 绿 / WARN 琥珀 / CRIT 红 / UNKNOWN 灰）。",
        note_fmt,
    )

    # ================= Local（RR §3：每主机每指标一行） =================
    ws = workbook.add_worksheet(SHEET_LOCAL)
    local_widths = (14, 34, 16, 14, 16, 8, 12, 46, 56, 52, 44)
    for col, width in enumerate(local_widths):
        ws.set_column(col, col, width)
    for col, header in enumerate(LOCAL_HEADERS):
        ws.write(0, col, header, header_fmt)
    ws.freeze_panes(1, 0)

    r = 1
    for doc in docs:
        host_name = doc["host"]["name"]
        for metric in doc["metrics"]:
            threshold = metric.get("threshold") or {}
            evidence = metric.get("evidence") or {}
            provenance = metric.get("provenance") or {}
            status = metric["status"]

            rule_parts = [
                str(x) for x in (threshold.get("rule_id"), threshold.get("value"))
                if x is not None and str(x) != ""
            ]
            rule = " | ".join(rule_parts) or threshold.get("layer") or "—"
            anchor = threshold.get("source_anchor") or "—"
            ev_summary = evidence.get("output_summary") or "—"
            prov_parts = [provenance.get("notes")]
            prov_parts += list(provenance.get("doc_sources") or [])
            prov_parts += list(provenance.get("config_sources") or [])
            provenance_text = "；".join(
                str(x) for x in prov_parts if x is not None and str(x) != ""
            ) or "—"

            ws.write(r, 0, host_name, cell_fmt)
            ws.write(r, 1, metric["metric_id"], cell_fmt)
            ws.write(r, 2, metric.get("name", ""), cell_fmt)
            # CRIT 值红色字体（用户需求）：raw_value / normalized_value
            value_fmt = crit_value_fmt if status == "CRIT" else cell_fmt
            ws.write(r, 3, metric["raw_value"], value_fmt)
            ws.write(r, 4, metric.get("normalized_value"), value_fmt)
            ws.write(r, 5, metric.get("unit", ""), cell_fmt)
            ws.write(r, 6, status, status_fmts[status])
            ws.write(r, 7, rule, cell_fmt)
            ws.write(r, 8, anchor, cell_fmt)
            ws.write(r, 9, ev_summary, cell_fmt)
            ws.write(r, 10, provenance_text, cell_fmt)
            r += 1

    # ============ Errors-Evidence（RR §3：error 非空指标与主机 +
    # 文档冲突/缺失 UNKNOWN 清单） ============
    ws = workbook.add_worksheet(SHEET_ERRORS)
    errors_widths = (14, 34, 16, 12, 24, 60, 48, 52, 44)
    for col, width in enumerate(errors_widths):
        ws.set_column(col, col, width)
    for col, header in enumerate(ERRORS_HEADERS):
        ws.write(0, col, header, header_fmt)
    ws.freeze_panes(1, 0)

    r = 1
    for doc in docs:
        host_name = doc["host"]["name"]
        for metric in doc["metrics"]:
            error = metric.get("error")
            status = metric["status"]
            if error is None and status != "UNKNOWN":
                continue
            evidence = metric.get("evidence") or {}
            threshold = metric.get("threshold") or {}
            provenance = metric.get("provenance") or {}
            if error is not None:
                err_code = error.get("code", "")
                message = error.get("message", "")
                note_parts = [
                    threshold.get("notes"), provenance.get("notes"),
                ]
            else:
                # 文档冲突/缺失导致的 UNKNOWN 清单（RR §3）
                err_code = ""
                message = ""
                note_parts = [
                    threshold.get("notes"), provenance.get("notes"),
                    threshold.get("layer"),
                ]
            note = "；".join(
                str(x) for x in note_parts if x is not None and str(x) != ""
            )
            status_fmt = status_fmts.get(status, status_fmts["UNKNOWN"])
            ws.write(r, 0, host_name, cell_fmt)
            ws.write(r, 1, metric["metric_id"], cell_fmt)
            ws.write(r, 2, metric.get("name", ""), cell_fmt)
            ws.write(r, 3, status, status_fmt)
            ws.write(r, 4, err_code, cell_fmt)
            ws.write(r, 5, message, cell_fmt)
            ws.write(r, 6, evidence.get("command") or "—", cell_fmt)
            ws.write(r, 7, evidence.get("output_summary") or "—", cell_fmt)
            ws.write(r, 8, note, cell_fmt)
            r += 1

    try:
        workbook.close()
    except Exception as exc:  # noqa: BLE001 — xlsxwriter 写失败均按渲染失败
        raise RendererError(f"Excel 写入失败: {target}（{exc}）") from exc


def render_xlsx(
    docs: Union[Mapping[str, Any], Sequence[Mapping[str, Any]]],
    out_path: Optional[Union[str, Path]] = None,
) -> Path:
    """渲染三 Sheet Excel 报表（只读消费 host-result-v1 文档）。

    - docs：单份 host-result-v1 文档，或同一次巡检的多主机文档序列
      （共享 inspection_id；Overview"主机×状态汇总"逐主机一行）；
    - out_path：None → `<inspection_id>.xlsx`（相对当前目录，RR §3
      文件名契约）；给定路径（`--xlsx-out` 语义）→ 覆盖默认路径；
    - 文档结构/计数不一致 → RendererError（exit_code=10）；xlsxwriter
      缺失 → RendererError（exit_code=10，明确报错不静默跳过）；
    - 返回实际写入的文件路径。
    """
    if isinstance(docs, Mapping):
        doc_list: List[Mapping[str, Any]] = [docs]
    else:
        doc_list = list(docs)
    if not doc_list:
        raise RendererError("没有可渲染的 host-result-v1 文档")
    for doc in doc_list:
        validate_doc(doc)
    inspection_id = doc_list[0]["inspection_id"]
    for doc in doc_list[1:]:
        if doc["inspection_id"] != inspection_id:
            raise RendererError(
                "多文档 inspection_id 不一致（同一次巡检共享 inspection_id，"
                f"HR §5/TD §3）: {doc['host']['name']} → {doc['inspection_id']!r} "
                f"≠ {inspection_id!r}"
            )
    target = (
        Path(out_path)
        if out_path is not None
        else Path.cwd() / f"{inspection_id}.xlsx"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RendererError(
            f"Excel 输出目录创建失败: {target.parent}（{exc}）"
        ) from exc
    _write_workbook(doc_list, target)
    return target


def render_xlsx_file(
    json_path: Union[str, Path],
    out_path: Optional[Union[str, Path]] = None,
) -> Path:
    """读取 host-result-v1 JSON 文件并渲染（渲染层只读 JSON，RR §1）。

    - 文件缺失/不可读/非法 JSON → RendererError（exit_code=10，损坏
      检测不静默）；
    - 文件内容为单文档对象或文档数组（同巡检多主机）；
    - 其余语义同 render_xlsx。
    """
    p = Path(json_path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RendererError(f"事实源 JSON 读取失败: {p}（{exc}）") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RendererError(f"事实源 JSON 损坏（解析失败）: {p}（{exc}）") from exc
    if isinstance(data, Mapping):
        return render_xlsx(data, out_path=out_path)
    if isinstance(data, list):
        return render_xlsx(data, out_path=out_path)
    raise RendererError(
        f"事实源 JSON 结构非法（期望 host-result-v1 对象或数组）: {p}"
    )


__all__ = [
    "COLOR_CRIT",
    "COLOR_OK",
    "COLOR_UNKNOWN",
    "COLOR_WARN",
    "ERRORS_HEADERS",
    "EXIT_RENDER_ERROR",
    "LOCAL_HEADERS",
    "RendererError",
    "SHEET_ERRORS",
    "SHEET_LOCAL",
    "SHEET_NAMES",
    "SHEET_OVERVIEW",
    "STATUS_COLORS",
    "VALID_STATUSES",
    "count_statuses",
    "render_xlsx",
    "render_xlsx_file",
    "validate_doc",
]
