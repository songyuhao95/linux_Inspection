"""T-101 CLI 行为测试：帮助文本、退出码、主机选择语义、--list-metrics/--info。

契约：docs/specs/cli-contract.md（§2 选项、§3 主机选择、§4 退出码、§5 帮助）。
测试以子进程驱动 `bash inspect.sh`（覆盖入口包装）；退出码映射逻辑另有单元测试。
"""

import subprocess
import sys

import pytest
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cli"

# 保证非 `python -m pytest` 调用方式下也能导入 inspect 包
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import inspect.cli as cli  # noqa: E402

ALL_METRIC_IDS = [
    "local.process.present",
    "local.service.active",
    "local.port.listening",
    "local.cpu.utilization",
    "local.cpu.load_1m",
    "local.memory.available_percent",
    "local.swap.used_percent",
    "local.filesystem.used_percent",
    "local.filesystem.inode_used_percent",
    "local.logs.key_evidence",
]

EXIT_CODE_TABLE_LINE = "退出码: 0 成功 / 2 用法错误 / 10 执行失败 / 20 业务告警"


def run_cli(*args, cwd=None):
    """以 `bash inspect.sh …` 子进程方式运行 CLI（与 AC 一致）。"""
    return subprocess.run(
        ["bash", "inspect.sh", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------- 帮助与只读查询

def test_help_exit_zero_and_contains_required_sections():
    """-h 退出码 0，且帮助含用法行/退出码表/主机选择示例/报表说明/脱敏声明（CC §5）。"""
    r = run_cli("-h")
    assert r.returncode == 0
    assert "用法" in r.stdout
    assert EXIT_CODE_TABLE_LINE in r.stdout
    assert "--hosts" in r.stdout and "--inventory" in r.stdout
    assert "--limit" in r.stdout and "--fail-on" in r.stdout
    assert "主机选择示例" in r.stdout
    assert "事实源与报表输出" in r.stdout
    assert "脱敏" in r.stdout


def test_help_contains_exit_code_table_exact_line():
    """AC-1 依赖的精确行（含分隔符）必须出现在帮助输出中。"""
    r = run_cli("--help")
    assert r.returncode == 0
    assert EXIT_CODE_TABLE_LINE in r.stdout


def test_list_metrics_lists_all_10_ids():
    """--list-metrics 退出码 0，输出全部 10 个 P0 指标 ID（不采集）。"""
    r = run_cli("--list-metrics")
    assert r.returncode == 0
    for mid in ALL_METRIC_IDS:
        assert mid in r.stdout


def test_info_metric_definition():
    """--info local.cpu.utilization 含数据源/单位/阈值层/来源锚点（CC §2）。"""
    r = run_cli("--info", "local.cpu.utilization")
    assert r.returncode == 0
    assert "local.cpu.utilization" in r.stdout
    assert "单位: %" in r.stdout
    assert "数据源" in r.stdout and "来源锚点" in r.stdout
    assert "巡检手册" in r.stdout


def test_info_unknown_metric_exit_2():
    """未知 --info ID → 明确错误 + 退出码 2。"""
    r = run_cli("--info", "local.no.such.metric")
    assert r.returncode == 2
    assert "未找到指标" in r.stderr


def test_list_metrics_with_info_mutual_exclusive():
    """--list-metrics 与 --info 互斥 → 退出码 2。"""
    r = run_cli("--list-metrics", "--info", "local.cpu.utilization")
    assert r.returncode == 2


# ---------------------------------------------------------------- 退出码（CC §4）

def test_unknown_option_exit_2():
    """未知选项 → 退出码 2（AC-3 第一段）。"""
    r = run_cli("--bogus")
    assert r.returncode == 2


def test_unsupported_middleware_option_exit_2():
    """未实现的中间件参数（如 --profile）→ 明确报“不支持” + 退出码 2（CC §1.4/§3）。"""
    r = run_cli("--profile", "kafka-unknown")
    assert r.returncode == 2
    assert "不支持" in r.stderr


def test_missing_option_value_exit_2():
    """选项缺参（-H 后无值）→ 退出码 2。"""
    r = run_cli("-H")
    assert r.returncode == 2


def test_default_no_args_is_local_inspection_not_usage_error():
    """无 -H/-i → 巡检本机语义：进入执行路径（真实执行未启用 → 10），而非用法错误 2。"""
    r = run_cli()
    assert r.returncode == 10
    assert (
        "真实 ansible-playbook 执行未启用" in r.stderr
        or "unsupported_control_platform" in r.stderr
        or "Linux or WSL" in r.stderr
    )


# ---------------------------------------------------------------- 主机选择语义（CC §3）

def test_local_and_hosts_mutex_exit_2():
    """--local 与 -H 同时给出 → 用法错误 2（AC-3 第二段）。"""
    r = run_cli("--local", "-H", "127.0.0.1")
    assert r.returncode == 2
    assert "互斥" in r.stderr


def test_local_and_inventory_mutex_exit_2():
    """--local 与 -i 同时给出 → 用法错误 2。"""
    r = run_cli("--local", "-i", str(FIXTURES / "hosts.yml"))
    assert r.returncode == 2
    assert "互斥" in r.stderr


def test_hosts_and_inventory_mutex_exit_2():
    """-H 与 -i 同时给出 → 用法错误 2。"""
    r = run_cli("-H", "10.0.0.11", "-i", str(FIXTURES / "hosts.yml"))
    assert r.returncode == 2
    assert "互斥" in r.stderr


def test_limit_requires_inventory_exit_2():
    """--limit 无 -i → 用法错误 2。"""
    r = run_cli("--limit", "db_servers")
    assert r.returncode == 2
    assert "--limit" in r.stderr


def test_all_requires_inventory_exit_2():
    """--all 无 -i → 用法错误 2。"""
    r = run_cli("--all")
    assert r.returncode == 2
    assert "--all" in r.stderr


def test_inventory_with_limit_is_valid_usage():
    """-i + --limit 合法组合：不是用法错误（inventory 解析失败 → 10）。"""
    r = run_cli("-i", str(FIXTURES / "hosts.yml"), "--limit", "db_servers")
    assert r.returncode == 10
    assert "inventory 解析失败" in r.stderr


def test_inventory_with_all_is_valid_usage():
    """-i + --all 合法组合（等价 --limit all）：管线未实现 → 10。"""
    r = run_cli("-i", str(FIXTURES / "hosts.yml"), "--all")
    assert r.returncode == 10


def test_hosts_comma_separated_is_valid_usage():
    """-H 逗号分隔列表：合法组合 → 10（管线未实现）。"""
    r = run_cli("-H", "10.0.0.11,10.0.0.12")
    assert r.returncode == 10


def test_missing_inventory_file_exit_2():
    """-i 路径不存在 → 用法错误 2（CC §7）。"""
    r = run_cli("-i", str(FIXTURES / "no-such-hosts.yml"))
    assert r.returncode == 2
    assert "inventory 文件不存在" in r.stderr


def test_excel_without_path_is_accepted():
    """--excel 可省略 PATH，空字符串表示使用当前工作目录。"""
    ns = cli.build_parser().parse_args(["--excel"])
    assert ns.excel == ""


def test_excel_with_explicit_path_is_accepted():
    """--excel PATH 直接携带 Excel 输出路径。"""
    ns = cli.build_parser().parse_args(["--excel", "report.xlsx"])
    assert ns.excel == "report.xlsx"


def test_html_without_path_is_accepted():
    """--html 可省略 PATH，空字符串表示使用当前工作目录。"""
    ns = cli.build_parser().parse_args(["--html"])
    assert ns.html == ""


def test_html_with_explicit_path_is_accepted():
    """--html PATH 直接携带 HTML 输出路径。"""
    ns = cli.build_parser().parse_args(["--html", "report.html"])
    assert ns.html == "report.html"


def test_report_output_paths_default_to_cwd_and_preserve_explicit_path(monkeypatch):
    """缺省路径使用 cwd，显式路径不被 out_dir 或 cwd 改写。"""
    expected_cwd = Path("C:/tmp/inspect-cli")
    monkeypatch.setattr(cli.Path, "cwd", staticmethod(lambda: expected_cwd))
    assert cli._report_output_path("", "inspection-1", ".xlsx") == (
        expected_cwd / "inspection-1.xlsx"
    )
    assert cli._report_output_path("reports/report.xlsx", "inspection-1", ".xlsx") == Path(
        "reports/report.xlsx"
    )


def test_xlsx_out_is_rejected():
    """旧参数 --xlsx-out 不再注册或接受。"""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--xlsx-out", "report.xlsx"])
    assert exc_info.value.code == 2


def test_html_out_is_rejected():
    """旧参数 --html-out 不再注册或接受。"""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--html-out", "report.html"])
    assert exc_info.value.code == 2


def test_query_with_inspection_args_exit_2():
    """--list-metrics/--info 为只读查询，不与其他巡检参数共用 → 2。"""
    r = run_cli("--list-metrics", "-H", "10.0.0.11")
    assert r.returncode == 2
    assert "只读查询" in r.stderr


# ---------------------------------------------------------------- 主机选择构造（单元）

def test_build_host_selection_local():
    """无 -H/-i → kind=local（本机）。"""
    sel = cli.build_host_selection(Namespace(inventory=None, hosts=None, all=False, limit=None))
    assert sel == {"kind": "local"}


def test_build_host_selection_hosts():
    """-H 逗号列表 → kind=hosts，去空白。"""
    sel = cli.build_host_selection(
        Namespace(inventory=None, hosts="10.0.0.11, 10.0.0.12", all=False, limit=None)
    )
    assert sel == {"kind": "hosts", "hosts": ["10.0.0.11", "10.0.0.12"]}


def test_build_host_selection_inventory_limit():
    """-i + --limit → kind=inventory 携带 limit。"""
    sel = cli.build_host_selection(
        Namespace(inventory="h.yml", hosts=None, all=False, limit="db*")
    )
    assert sel == {"kind": "inventory", "inventory": "h.yml", "limit": "db*"}


def test_build_host_selection_inventory_all():
    """-i + --all → kind=inventory 且 limit=all（等价 --limit all）。"""
    sel = cli.build_host_selection(
        Namespace(inventory="h.yml", hosts=None, all=True, limit=None)
    )
    assert sel == {"kind": "inventory", "inventory": "h.yml", "limit": "all"}


# ---------------------------------------------------------------- 退出码映射（单元）

def test_exit_code_mapping_priority():
    """优先级 2 > 10 > 20 > 0（CC §4）。"""
    # 用法错误压过一切
    assert cli.compute_exit_code(usage_error=True) == 2
    assert cli.compute_exit_code(usage_error=True, execution_error=True) == 2
    assert cli.compute_exit_code(
        usage_error=True, execution_error=True, has_crit=True, fail_on_critical=True
    ) == 2
    # 技术失败（10）优先于业务告警（20）
    assert cli.compute_exit_code(execution_error=True) == 10
    assert cli.compute_exit_code(
        execution_error=True, has_crit=True, fail_on_critical=True
    ) == 10
    # 业务告警仅 --fail-on critical + CRIT
    assert cli.compute_exit_code(has_crit=True, fail_on_critical=True) == 20
    assert cli.compute_exit_code(has_crit=True) == 0        # 默认仅报告
    assert cli.compute_exit_code(fail_on_critical=True) == 0  # 无 CRIT 不触发
    assert cli.compute_exit_code() == 0
