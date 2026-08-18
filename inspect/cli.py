"""inspect 命令行入口（T-101：参数解析、主机选择、退出码映射、编排主体）。

模块边界（docs/specs/technical-design.md §4）：本模块只做 argparse 解析、
主机选择校验、退出码 0/2/10/20 映射与编排（run_inspection），不实现采集/
解析/渲染/连接逻辑。采集（T-103）、normalize（T-104）、事实源（T-104）、
报表渲染（T-105/106/107）由 run_inspection() 按 technical-design §2
单向数据流编排：采集 → normalize → 原子写 JSON → 报表（报表只消费 JSON）。
下游模块异常统一映射执行失败（10，用法级为 2），不伪造业务结论。

CLI 契约：docs/specs/cli-contract.md（选项表 §2、主机选择 §3、退出码 §4、帮助 §5）。
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from inspect import ansible_runner as runner_mod
from inspect import config as config_mod
from inspect import fact_source as fact_source_mod
from inspect import inventory as inventory_mod
from inspect import local_runner
from inspect import metrics as metrics_registry
from inspect import normalize as normalize_mod
from inspect import render_html as html_mod
from inspect import render_stdout as stdout_mod
from inspect import render_xlsx as xlsx_mod

# cli-contract §4 退出码
EXIT_OK = 0      # 成功（含业务 WARN/CRIT 但未启用 --fail-on critical）
EXIT_USAGE = 2   # 用法错误：未知选项、参数缺失、互斥、不支持的中间件选择
EXIT_EXEC = 10   # 执行失败（技术）：控制端/管线失败，与业务状态无关
EXIT_CRIT = 20   # 业务告警：仅 --fail-on critical 且任一指标 status=CRIT


def compute_exit_code(
    *,
    usage_error: bool = False,
    execution_error: bool = False,
    has_crit: bool = False,
    fail_on_critical: bool = False,
) -> int:
    """退出码映射，优先级 2 > 10 > 20 > 0（cli-contract §4）。

    技术失败（10）优先于业务告警（20）：执行失败时不得再产生业务结论；
    --fail-on critical 仅响应业务 CRIT，WARN/UNKNOWN 不触发 20。
    """
    if usage_error:
        return EXIT_USAGE
    if execution_error:
        return EXIT_EXEC
    if fail_on_critical and has_crit:
        return EXIT_CRIT
    return EXIT_OK


class InspectArgumentParser(argparse.ArgumentParser):
    """用法错误统一输出到 stderr，并以退出码 2 结束（cli-contract §4）。"""

    def error(self, message):  # noqa: D102
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: 错误: {message}\n")


_HELP_EPILOG = """主机选择示例:
  inspect.sh                                          # 巡检本机（无 -H/-i 时默认本机）
  inspect.sh -H inspection                                   # 使用默认 inventory 主机组
  inspect.sh -H 10.0.0.11,10.0.0.12                         # 按主机名/IP选择（逗号分隔）
  inspect.sh -i inventory/hosts.yml --limit 'db*'     # inventory 主机模式
  inspect.sh -i inventory/hosts.yml --all             # inventory 全部主机

事实源与报表输出:
  每主机生成 out/<inspection-id>/hosts/<host>.json（host-result-v1，原子写）；
  --excel/--html 生成 Excel 与离线单文件 HTML 报表（路径由 --xlsx-out/--html-out 覆盖）。

执行路径:
  --local 直接执行本机只读探测/指标命令，不调用 Ansible；
  -H/--hosts 或 -i/--inventory 使用项目内打包的 Ansible；
  INSPECT_FIXTURE_DIR 为两种模式共用的零连接调试路径。

退出码: 0 成功 / 2 用法错误 / 10 执行失败 / 20 业务告警(--fail-on critical)

脱敏声明: 本工具为只读巡检，不修改目标主机配置、不写入业务数据、不导入凭据；
输出中的 IP、凭据等敏感信息按配置边界脱敏（监听 IP 脱敏为 <IP>）。
"""


def build_parser() -> argparse.ArgumentParser:
    """cli-contract §2 选项总表（冻结集，不新增选项）。"""
    parser = InspectArgumentParser(
        prog="inspect.sh",
        description="中间件运维巡检 CLI（local 垂直切片，默认 6 个 Linux 基础指标）："
                    "只读巡检本机或远程主机，输出事实源与三类报表。",
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-H", "--hosts", metavar="group-or-ip[,group-or-ip]",
        help=(
            "按默认 inventory/hosts.ini 的主机组、主机名或 IP 巡检；"
            "无默认 inventory 时生成临时主机列表"
        ),
    )
    parser.add_argument("-i", "--inventory", metavar="PATH", help="使用已有 inventory")
    parser.add_argument(
        "--limit", metavar="PATTERN", help="inventory 主机模式（与 --inventory 搭配）",
    )
    parser.add_argument("--local", action="store_true", help="显式巡检本机（默认）")
    parser.add_argument("--all", action="store_true", help="inventory 全部主机")
    parser.add_argument(
        "--list-metrics", action="store_true", help="列出已实现指标，不采集",
    )
    parser.add_argument("--info", metavar="METRIC_ID", help="显示指标定义，不采集")
    parser.add_argument("-e", "--excel", action="store_true", help="生成 Excel 报表")
    parser.add_argument("--xlsx-out", metavar="PATH", help="Excel 输出路径")
    parser.add_argument("--html", action="store_true", help="生成离线单文件 HTML 报表")
    parser.add_argument("--html-out", metavar="PATH", help="HTML 输出路径")
    parser.add_argument(
        "--fail-on", dest="fail_on", nargs="?", const="critical",
        choices=("critical",),
        help="业务告警开关（--fail-on critical）：任一指标 CRIT 时退出码 20",
    )
    return parser


def validate_args(ns: argparse.Namespace) -> List[str]:
    """主机选择语义校验（cli-contract §3/§7）；返回用法错误列表，空 = 合法。"""
    errors: List[str] = []
    if ns.hosts and ns.inventory:
        errors.append("-H/--hosts 与 -i/--inventory 互斥，请二选一")
    if ns.local and (ns.hosts or ns.inventory):
        errors.append("--local 与 -H/--hosts、-i/--inventory 互斥")
    if ns.limit and not ns.inventory:
        errors.append("--limit 仅可与 --inventory 一起使用")
    if ns.all and not ns.inventory:
        errors.append("--all 仅可与 --inventory 一起使用")
    if ns.xlsx_out and not ns.excel:
        errors.append("--xlsx-out 需与 --excel 一起使用")
    if ns.html_out and not ns.html:
        errors.append("--html-out 需与 --html 一起使用")
    query = ns.list_metrics or bool(ns.info)
    if query and (
        ns.hosts or ns.inventory or ns.local or ns.limit or ns.all
        or ns.excel or ns.html or ns.fail_on or ns.xlsx_out or ns.html_out
    ):
        errors.append("--list-metrics/--info 为只读查询，不与其他巡检/报表参数共用")
    if ns.list_metrics and ns.info:
        errors.append("--list-metrics 与 --info 互斥")
    if ns.inventory and not Path(ns.inventory).is_file():
        errors.append(f"inventory 文件不存在: {ns.inventory}（用法错误）")
    return errors


def build_host_selection(ns: argparse.Namespace) -> Dict[str, object]:
    """主机选择语义（cli-contract §3）→ 供 T-103 inventory 层挂接。"""
    if ns.inventory:
        return {
            "kind": "inventory",
            "inventory": ns.inventory,
            "limit": "all" if ns.all else ns.limit,
        }
    if ns.hosts:
        hosts = [h.strip() for h in ns.hosts.split(",") if h.strip()]
        return {"kind": "hosts", "hosts": hosts}
    return {"kind": "local"}


def print_metrics_list() -> None:
    """--list-metrics：注册表只读输出（ID、名称、阈值层、来源锚点；不采集不连接）。"""
    reg = metrics_registry
    print(f"已实现指标（{reg.VERSION}，共 {reg.count_metrics()} 个；只读查询，不采集）")
    print(f"{'metric_id':<38} {'名称':<16} {'阈值层':<34} 来源锚点（摘要）")
    for m in reg.iter_metrics():
        anchor = m["source_anchor"].split("；")[0]
        print(f"{m['metric_id']:<38} {m['name']:<16} {m['threshold_layer']:<34} {anchor}")


def show_metric_info(metric_id: str) -> int:
    """--info METRIC_ID：单指标定义只读输出；未知 ID → 用法错误（退出码 2）。"""
    m = metrics_registry.get_metric(metric_id)
    if m is None:
        print(
            f"inspect.sh: 错误: 未找到指标: {metric_id}（可执行 --list-metrics 查看全部）",
            file=sys.stderr,
        )
        return EXIT_USAGE
    print(f"指标: {m['metric_id']}（{m['name']}）")
    print(f"数据源: {m['command']}")
    print(f"单位: {m['unit']}")
    print(f"阈值层: {m['threshold_layer']}")
    print(f"阈值规则: {'、'.join(m['threshold_rule_ids'])}")
    print(f"来源锚点: {m['source_anchor']}")
    print(f"文档基线: {m['doc_baseline']}")
    print(f"冲突/备注: {'；'.join(m['conflicts']) if m['conflicts'] else '无'}")
    print(f"UNKNOWN 条件: {m['unknown_conditions']}")
    print(f"超时: {m['timeout_sec']}s | 解析器: {m['parser']}")
    return EXIT_OK


def _fail(exc: BaseException) -> int:
    """统一输出下游异常并映射退出码（下游异常携带 .exit_code；缺省执行失败 10）。

    用法级错误（exit_code=2，如主机选择解析失败）沿用 "inspect.sh: 错误"
    前缀，与 validate_args 输出风格一致；其余均为技术失败（10）。
    """
    code = getattr(exc, "exit_code", EXIT_EXEC)
    prefix = "inspect.sh: 错误" if code == EXIT_USAGE else "inspect.sh: 执行失败"
    print(f"{prefix}: {exc}", file=sys.stderr)
    return code


def _make_run_id() -> str:
    """每次巡检独立 run_id（run-<日期>-<随机6位>；TD §11 回滚可追溯）。"""
    return f"run-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6]}"


def _inventory_source(host_selection: object) -> str:
    """normalize 的 inventory_source：inventory 模式记录文件路径，其余取 kind。"""
    kind = host_selection.kind
    if kind == "inventory":
        return str(host_selection.inventory_file)
    return kind


def run_inspection(ns: argparse.Namespace, selection: Dict[str, object]) -> int:
    """巡检编排主体（TD §2 单向数据流：采集 → normalize → 原子写 JSON → 报表）。

    步骤：
      1. 配置加载（inspect.yml 可选，缺省 out_dir=out）与阈值合并（文档基线）；
      2. 主机选择解析（inventory.py；-H/-i/--limit/--all，用法错误 2 / 执行失败 10）；
      3. 指标命令规格：默认只选择 linux_basic 的 6 个 profile-free 基础指标；
         未显式选择中间件模块时，linux_common 不进入执行计划；
      4. 执行：--local 走 local_runner 直接执行本机 shell，完全不调用
         Ansible；-H/--hosts 与 -i/--inventory 走 ansible_runner 的项目内
         Ansible；INSPECT_FIXTURE_DIR 两种模式均为零连接调试路径；
      5. normalize（host-result-v1 文档 + 主机错误明细）；
      6. 原子写事实源（fact_source；inspection_id 唯一，重跑不覆盖，TD §11）；
      7. 报表渲染只消费 JSON（RR §1）：stdout 摘要（读事实源）→ Excel
         （-e/--xlsx-out；xlsxwriter 缺失按 T-106 语义报错退出码 10，
         不中断其余输出）→ HTML（--html/--html-out）；
      8. 退出码：2 > 10 > 20 > 0（cli-contract §4）。
    """
    try:
        cfg = config_mod.load_inspect_config()
        resolved_thresholds = config_mod.build_resolved_thresholds()
    except config_mod.ConfigError as exc:
        return _fail(exc)
    out_dir = Path(cfg["out_dir"])

    runtime_dir = inventory_mod.default_runtime_dir()
    try:
        host_selection = inventory_mod.resolve_host_selection(selection, runtime_dir)
    except inventory_mod.InventoryError as exc:
        return _fail(exc)

    specs = runner_mod.build_metric_command_specs()
    fixture_dir = os.environ.get(runner_mod.FIXTURE_ENV_VAR)
    try:
        if host_selection.kind == "local":
            run_result = local_runner.run_local(
                host_selection, specs, fixture_dir=fixture_dir, runtime_dir=runtime_dir
            )
        else:
            run_result = runner_mod.run(
                host_selection, specs, fixture_dir=fixture_dir, runtime_dir=runtime_dir
            )
    except (
        local_runner.LocalExecutionError,
        runner_mod.ExecutionNotReadyError,
        runner_mod.RealExecutionError,
        runner_mod.FixtureError,
        runner_mod.CommandNotAllowedError,
        runner_mod.CommandConfigError,
    ) as exc:
        return _fail(exc)

    # 技术连接/探测失败与业务指标状态分离：即使事实源可落盘，任一主机
    # host_error 仍必须让 CLI 返回 10；单指标 UNKNOWN/PARTIAL 不走此分支。
    execution_error = (
        run_result.get("execution_status") == runner_mod.STATUS_ERROR
        or any(host.get("host_error") for host in run_result.get("hosts", []))
    )

    collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
    inspection_id = normalize_mod.make_inspection_id(
        host_selection.hosts[0].name, datetime.fromisoformat(collected_at)
    )
    run_id = _make_run_id()
    normalized = normalize_mod.normalize_run_results(
        run_result,
        run_id=run_id,
        inspection_id=inspection_id,
        collected_at=collected_at,
        profile=None,
        product_profiles=[],
        resolved_thresholds=resolved_thresholds,
        inventory_source=_inventory_source(host_selection),
        meta=None,
    )
    try:
        written = fact_source_mod.write_inspection(
            out_dir,
            run_id,
            inspection_id,
            normalized["documents"],
            normalized["host_errors"],
        )
        # 渲染只消费 JSON（RR §1）：stdout 由 render_stdout 读事实源目录；
        # Excel/HTML 从已落盘的 host-result-v1 文档读回渲染（零二次采集）。
        facts_docs = [
            fact_source_mod.read_host_result(Path(entry["file"]))
            for entry in written["entries"]
        ]
    except fact_source_mod.FactSourceError as exc:
        return _fail(exc)

    print(f"事实源: {written['inspection_dir']}（inspection_id={inspection_id}）")
    try:
        print(stdout_mod.render_inspection_report(out_dir, inspection_id, stream=sys.stdout))
    except fact_source_mod.FactSourceError as exc:
        return _fail(exc)

    if ns.excel:
        xlsx_path = Path(ns.xlsx_out) if ns.xlsx_out else out_dir / f"{inspection_id}.xlsx"
        try:
            xlsx_mod.render_xlsx(facts_docs, out_path=xlsx_path)
        except xlsx_mod.RendererError as exc:
            print(f"inspect.sh: 执行失败: {exc}", file=sys.stderr)
            execution_error = True
        else:
            print(f"Excel 报表: {xlsx_path}")

    if ns.html:
        html_path = Path(ns.html_out) if ns.html_out else out_dir / f"{inspection_id}.html"
        try:
            html_mod.render_html(facts_docs, out_path=html_path)
        except html_mod.RenderHtmlError as exc:
            print(f"inspect.sh: 执行失败: {exc}", file=sys.stderr)
            execution_error = True
        else:
            print(f"HTML 报表: {html_path}")

    has_crit = any(
        m["status"] == normalize_mod.STATUS_CRIT
        for doc in facts_docs
        for m in doc["metrics"]
    )
    return compute_exit_code(
        execution_error=execution_error,
        has_crit=has_crit,
        fail_on_critical=ns.fail_on,
    )


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    ns, unknown = parser.parse_known_args(argv)
    if unknown:
        # cli-contract §1.4/§3：未实现/未知参数明确报“不支持”，退出码 2
        parser.error("不支持: " + " ".join(unknown))

    errors = validate_args(ns)
    if errors:
        for msg in errors:
            print(f"inspect.sh: 错误: {msg}", file=sys.stderr)
        return EXIT_USAGE

    if ns.list_metrics:
        return print_metrics_list() or EXIT_OK
    if ns.info:
        return show_metric_info(ns.info)

    selection = build_host_selection(ns)
    return run_inspection(ns, selection)


def _reconfigure_stdio() -> None:
    """stdout/stderr 强制 UTF-8（控制端 locale 与管道消费方可能不一致）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _reconfigure_stdio()
    sys.exit(main())
