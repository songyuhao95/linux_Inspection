"""tests/test_e2e.py — T-108 端到端（fixture 全链路 + 回滚演练）。

契约：contract-T-108-v1（AC-1 语义）+ technical-design §2（单向数据流：
采集 → normalize → 原子写 JSON → 报表，报表只消费 JSON）/§10（fixture
调试模式零连接）/§11（回滚演练）+ reporting-roadmap §1（报表只读 JSON）。

全部 e2e 以 fixture 模式驱动（INSPECT_FIXTURE_DIR=tests/fixtures/e2e）：
CLI 子进程经 bash inspect.sh 启动，ansible_runner 从夹具读取预录输出，
零真实连接、零命令执行、无目标主机；stderr 必须含"调试模式（fixture）"
声明（TD §10.2/REQ-N-08）。本文件不发起任何网络/远端访问。

回滚演练（TD §11）：两次连续运行产生不同 inspection_id（秒级精度，
两运行间 sleep 1.1s）、旧 JSON 未被覆盖、旧 JSON 可独立重渲染三类报表。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "e2e"
FIXTURE_ENV_VAR = "INSPECT_FIXTURE_DIR"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inspect import fact_source, normalize, render_html, render_stdout, render_xlsx  # noqa: E402

# render_stdout 报表行：`  inspection_id: insp-YYYYMMDDHHMMSS-<safe-host>`
INSP_ID_RE = re.compile(r"inspection_id: (insp-\d{14}-[\w.-]+)")
# render_html 内嵌数据块：`<script type="application/json" id="inspection-data">…</script>`
EMBED_RE = re.compile(
    r'<script type="application/json" id="inspection-data">(.*?)</script>',
    re.S,
)


@pytest.fixture(scope="session", autouse=True)
def _clean_runtime_artifacts():
    """会话收尾清理 <repo root>/.runtime（CLI 运行期临时 inventory/playbook）。

    运行时目录为仓库根 .runtime/（inventory.default_runtime_dir，基于
    __file__ 定位，与 cwd 无关）；该目录不在 .gitignore（仅 run/.runtime/
    被忽略），pytest 全量回归后清理，保持工作树 git 状态零污染。
    """
    yield
    shutil.rmtree(REPO_ROOT / ".runtime", ignore_errors=True)


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """以 fixture 模式运行 CLI（bash inspect.sh 子进程；零连接）。

    cwd=tmp_path 使 out_dir（默认 "out"）落在临时目录；脚本以绝对路径
    调用（inspect.sh 经 BASH_SOURCE 定位包路径，任意 cwd 均可运行）。
    """
    env = dict(os.environ)
    env[FIXTURE_ENV_VAR] = str(FIXTURES)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "inspect.sh"), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def extract_inspection_id(stdout: str) -> str:
    """从 stdout 报表行提取 inspection_id（`inspection_id: <id>`）。"""
    m = INSP_ID_RE.search(stdout)
    assert m, "stdout 未含 inspection_id 行:\n" + stdout
    return m.group(1)


def assert_doc(doc, inspection_id: str, host: str) -> None:
    """事实源 host-result-v1 文档断言：计数与夹具预期一致（OK=4/UNKNOWN=6）。"""
    assert doc["inspection_id"] == inspection_id
    assert doc["host"]["name"] == host
    es = doc["execution_summary"]
    assert es["total_metrics"] == 10
    assert es["ok"] == 4 and es["warn"] == 0 and es["crit"] == 0
    assert es["unknown"] == 6
    assert es["executed"] == 4 and es["failed"] == 6
    assert doc["execution_status"] == normalize.STATUS_PARTIAL
    normalize.validate_host_result(doc)  # schema 校验（合同 AC 语义）


def test_local_full_chain_fixture_declared(tmp_path):
    """--local fixture 全链路：CLI→采集→normalize→JSON→stdout 报表，零连接。

    断言 stderr 调试模式声明（TD §10.2）、stdout 报表计数与事实源 JSON
    一致（RR §1：报表只消费 JSON）、索引 sha256 与事实源一致。
    """
    r = run_cli("--local", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    # stderr 声明调试模式（fixture）：未发起任何连接
    assert "调试模式（fixture）" in r.stderr
    assert "未发起任何连接" in r.stderr
    assert FIXTURE_ENV_VAR in r.stderr
    # stdout 报表（render_stdout 只读事实源）
    assert "巡检报告" in r.stdout
    insp_id = extract_inspection_id(r.stdout)
    assert "（OK=4 WARN=0 CRIT=0 UNKNOWN=6）" in r.stdout
    assert "executed=4 failed=6" in r.stdout
    # 事实源：目录布局 out/<inspection_id>/hosts/<host>.json + 索引
    out = tmp_path / "out"
    host_json = out / insp_id / "hosts" / "localhost.json"
    assert host_json.is_file(), "事实源 host JSON 未生成"
    doc = json.loads(host_json.read_text(encoding="utf-8"))
    assert_doc(doc, insp_id, "localhost")
    assert doc["host"]["inventory_source"] == "local"
    index = json.loads(
        (out / insp_id / f"inspection-{insp_id}-index.json")
        .read_text(encoding="utf-8")
    )
    assert index["inspection_id"] == insp_id
    entry = next(h for h in index["hosts"] if h["host"] == "localhost")
    assert entry["sha256"] == fact_source.sha256_bytes(host_json.read_bytes())
    assert entry["execution_status"] == normalize.STATUS_PARTIAL


def test_inventory_selection_fixture_chain(tmp_path):
    """-i hosts.yml --limit e2e-web：inventory 选择路径全链路（无目标主机）。"""
    r = run_cli("-i", str(FIXTURES / "hosts.yml"), "--limit", "e2e-web", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "调试模式（fixture）" in r.stderr
    insp_id = extract_inspection_id(r.stdout)
    host_json = tmp_path / "out" / insp_id / "hosts" / "e2e-node-1.json"
    assert host_json.is_file(), "inventory 选择路径事实源未生成"
    doc = json.loads(host_json.read_text(encoding="utf-8"))
    assert_doc(doc, insp_id, "e2e-node-1")
    assert doc["host"]["inventory_source"].endswith("hosts.yml")


def test_html_report_consumes_fact_source_only(tmp_path):
    """--html：离线单文件 HTML 内嵌 JSON 与事实源逐字节一致（报表只消费 JSON）。"""
    r = run_cli("--local", "--html", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    insp_id = extract_inspection_id(r.stdout)
    assert "HTML 报表" in r.stdout
    html_path = tmp_path / "out" / f"{insp_id}.html"
    assert html_path.is_file(), "HTML 报表未生成"
    text = html_path.read_text(encoding="utf-8")
    m = EMBED_RE.search(text)
    assert m, "HTML 缺内嵌 JSON 数据块"
    embedded = json.loads(m.group(1))
    doc = json.loads(
        (tmp_path / "out" / insp_id / "hosts" / "localhost.json")
        .read_text(encoding="utf-8")
    )
    assert len(embedded) == 1
    assert embedded[0] == doc, "HTML 内嵌 JSON 与事实源不一致"
    # 宏观计数与事实源一致（OK/WARN/CRIT/UNKNOWN = 4/0/0/6）
    assert "4 / 0 / 0 / 6" in text


def test_excel_missing_xlsxwriter_error_path(tmp_path):
    """xlsxwriter 未安装：-e → 退出码 10 + stderr 明确报错，不中断其余输出。

    T-106 语义：Excel 渲染失败（RendererError exit_code=10）不阻断
    stdout 报表/HTML/事实源；最终退出码 10（技术失败优先）。
    """
    r = run_cli("--local", "-e", "--html", cwd=tmp_path)
    assert r.returncode == 10, f"rc={r.returncode}\n{r.stderr}"
    assert "xlsxwriter 未安装，无法生成 Excel" in r.stderr
    # 其余输出不中断：事实源、stdout 报表、HTML 均已产出
    assert "巡检报告" in r.stdout
    insp_id = extract_inspection_id(r.stdout)
    out = tmp_path / "out"
    assert (out / insp_id / "hosts" / "localhost.json").is_file()
    assert (out / f"{insp_id}.html").is_file()
    assert not (out / f"{insp_id}.xlsx").exists()


def test_rerun_new_inspection_id_old_json_untouched(tmp_path):
    """回滚演练一：重跑生成新 inspection_id，旧 JSON 未被覆盖（TD §11）。"""
    r1 = run_cli("--local", cwd=tmp_path)
    assert r1.returncode == 0, r1.stderr
    insp1 = extract_inspection_id(r1.stdout)
    old_json = tmp_path / "out" / insp1 / "hosts" / "localhost.json"
    old_bytes = old_json.read_bytes()
    # inspection_id 秒级精度：两运行须落在不同秒，保证 ID 不同
    time.sleep(1.1)
    r2 = run_cli("--local", cwd=tmp_path)
    assert r2.returncode == 0, r2.stderr
    insp2 = extract_inspection_id(r2.stdout)
    assert insp1 != insp2, "重跑应生成新 inspection_id（TD §11 事实源不覆盖）"
    assert old_json.read_bytes() == old_bytes, "旧 JSON 被覆盖（回滚保障破坏）"
    assert (tmp_path / "out" / insp2 / "hosts" / "localhost.json").is_file()


def test_old_inspection_independently_rerendered(tmp_path, monkeypatch):
    """回滚演练二：旧 JSON 可独立重渲染三类报表（报表只读 JSON，不重采集）。"""
    r = run_cli("--local", "--html", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    insp_id = extract_inspection_id(r.stdout)
    out = tmp_path / "out"
    host_json = out / insp_id / "hosts" / "localhost.json"
    # stdout：render_stdout 从旧 JSON 目录独立重渲染。索引 file 条目为
    # CLI 运行 cwd（tmp_path）相对路径，故在相同 cwd 下渲染（与 CLI
    # 自身渲染路径完全一致，TD §11 报表可随时重生成）
    monkeypatch.chdir(tmp_path)
    report = render_stdout.render_inspection_report("out", insp_id)
    assert f"inspection_id: {insp_id}" in report
    assert "（OK=4 WARN=0 CRIT=0 UNKNOWN=6）" in report
    # HTML：render_html_from_files 从旧 JSON 文件独立重渲染
    rerendered_html = tmp_path / "rerendered.html"
    render_html.render_html_from_files([host_json], out_path=rerendered_html)
    text = rerendered_html.read_text(encoding="utf-8")
    m = EMBED_RE.search(text)
    assert m, "重渲染 HTML 缺内嵌 JSON"
    doc = json.loads(host_json.read_text(encoding="utf-8"))
    assert json.loads(m.group(1)) == [doc]
    assert "4 / 0 / 0 / 6" in text
    # Excel：render_xlsx_file 从旧 JSON 文件独立重渲染；本环境 xlsxwriter
    # 缺失 → JSON 校验通过后于库导入处报 RendererError（T-106 语义；
    # 真实渲染由集成环境 TestRenderWorkbook 验证）
    with pytest.raises(render_xlsx.RendererError, match="xlsxwriter 未安装"):
        render_xlsx.render_xlsx_file(
            host_json, out_path=tmp_path / "rerendered.xlsx"
        )
