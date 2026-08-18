"""tests/test_render_stdout.py — T-105 stdout 渲染测试（合同 AC-1）。

覆盖（RR §2/§5、HR §8、TD §8；REQ-R-01/02/07）：
  - run 摘要与主机摘要：execution_status 徽标 + 四状态计数与 JSON
    execution_summary 一致（RR §6.1 展示层不做二次计算）；
  - 顺序：先全局（run 摘要）后逐主机（主机摘要 → 失败/未知列表 → 退出码）；
  - UNKNOWN/ERROR 显式原因：missing / conflict / permission / timeout /
    other:<code>（REQ-R-02，不得静默过滤）；
  - execution_status != SUCCESS → 技术失败计数（executed/failed）显式展示
    不掩盖（HR §8）；ERROR 主机无业务结论（AE §6）；
  - 无颜色环境（NO_COLOR / TERM=dumb / 非 TTY）符号/缩写区分；force 强制
    彩色时徽标颜色正确（REQ-R-07）；
  - 渲染零采集：mock 断言 ansible_runner.run / subprocess.run 零调用 +
    模块源码导入边界检查（REQ-N-06）；
  - 退出码说明（cli-contract §4）；
  - 事实源目录渲染（TD §3 布局，只读；损坏 JSON → FactSourceError）。

只读消费 tests/fixtures/stdout/（本任务）与 tests/fixtures/json/（T-104，
只读）夹具；不连接、不执行命令。
"""

import copy
import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from inspect import fact_source as fs
from inspect import normalize as n
from inspect import render_stdout as r

FIXTURE_STDOUT = Path(__file__).parent / "fixtures" / "stdout"
FIXTURE_JSON = Path(__file__).parent / "fixtures" / "json"
RUN_ID = "run-20260814-001"
INSPECTION_ID = "insp-20260814120000-node-fx01"

# 主机级 ERROR 明细（与汇总索引承载一致；事实源 schema 无主机级 error
# 字段，T-104 报告 D1）
ERROR_DETAIL = {
    "node-fx03": {
        "code": "CONNECTION_FAILED",
        "message": "SSH 连接被拒绝（connection refused）",
        "metric_status": "UNKNOWN",
    }
}


def load(name: str) -> dict:
    return json.loads((FIXTURE_STDOUT / name).read_text(encoding="utf-8"))


def partial_doc() -> dict:
    """PARTIAL 主机：9 指标，覆盖四类原因与四业务状态混排。"""
    return load("host-result-partial.json")


def error_doc() -> dict:
    """ERROR 主机（AE §6：metrics=[], executed=0, failed=3）。"""
    return load("host-result-error.json")


def valid_doc() -> dict:
    """SUCCESS 样例（T-104 夹具，只读）。"""
    return json.loads((FIXTURE_JSON / "host-result-valid.json").read_text(encoding="utf-8"))


def host_errors() -> dict:
    return dict(ERROR_DETAIL)


def render(*docs, host_errors=None, color=False) -> str:
    return r.render_report(list(docs), host_errors=host_errors, color=color)


# --------------------------------------------------------------------------
# 0. 夹具自检（与 T-104 同质量：host-result-v1 schema 语义校验）
# --------------------------------------------------------------------------


class TestFixtures:
    def test_fixtures_are_schema_valid(self):
        for name in ("host-result-partial.json", "host-result-error.json"):
            doc = load(name)
            n.validate_host_result(doc)  # 违反 → ValueError
        n.validate_host_result(valid_doc())

    def test_partial_fixture_covers_reason_taxonomy(self):
        doc = partial_doc()
        unknown = [m for m in doc["metrics"] if m["status"] == "UNKNOWN"]
        reasons = sorted({r.classify_unknown_reason(m) for m in unknown})
        assert reasons == ["conflict", "missing", "other:parse_failed", "permission", "timeout"]
        statuses = {m["status"] for m in doc["metrics"]}
        assert statuses == {"OK", "WARN", "CRIT", "UNKNOWN"}


# --------------------------------------------------------------------------
# 1. run 摘要 / 主机摘要：状态计数与 JSON 一致（REQ-R-01，RR §6.1）
# --------------------------------------------------------------------------


class TestSummaryConsistency:
    def test_host_counts_match_json(self):
        doc = partial_doc()
        out = render(doc)
        s = doc["execution_summary"]
        assert (
            f"OK={s['ok']} WARN={s['warn']} CRIT={s['crit']} UNKNOWN={s['unknown']}"
            in out
        )
        assert f"executed={s['executed']} failed={s['failed']}" in out

    def test_run_aggregation_matches_json(self):
        docs = [valid_doc(), partial_doc(), error_doc()]
        out = render(*docs, host_errors=host_errors())
        # valid: total=1 ok=1；partial: total=9 ok=1 warn=1 crit=1 unknown=6
        # executed=5 failed=4；error: total=3 executed=0 failed=3
        assert "OK=2 WARN=1 CRIT=1 UNKNOWN=6" in out
        assert "executed=6 failed=7" in out
        assert "主机数:        3（ERROR=1 PARTIAL=1 SUCCESS=1）" in out
        assert "run-20260814-001" in out
        assert INSPECTION_ID in out

    def test_execution_badges(self):
        out = render(valid_doc(), partial_doc(), error_doc(), host_errors=host_errors())
        assert "[SUCCESS]" in out
        assert "[PARTIAL]" in out
        assert "[ERROR]" in out

    def test_error_host_no_business_conclusion(self):
        out = render(error_doc(), host_errors=host_errors())
        assert "无业务结论" in out
        assert "executed=0 failed=3" in out

    def test_section_order_global_first(self):
        out = render(partial_doc())
        lines = out.splitlines()
        pos = {ln: i for i, ln in enumerate(lines) if not ln.startswith("  ") and not ln.startswith("    ")}
        assert pos["run 摘要"] < pos["主机摘要"] < pos["失败/未知指标列表（UNKNOWN/ERROR 显式原因，RR §2）"] < pos["退出码说明（cli-contract §4）"]


# --------------------------------------------------------------------------
# 1A. 已执行指标值从 JSON 事实源以中文字段名输出
# --------------------------------------------------------------------------


class TestMetricValueOutput:
    def test_metric_values_use_chinese_json_name_and_normalized_value(self):
        out = render(valid_doc())
        assert "指标结果（从 JSON 事实源读取）" in out
        assert "Swap 使用率: 0.00 %" in out
        assert "local.swap.used_percent" not in out

    def test_filesystem_metrics_render_each_mount_from_json_details(self):
        doc = valid_doc()
        template = copy.deepcopy(doc["metrics"][0])

        def filesystem_metric(metric_id, name, details, max_pct):
            metric = copy.deepcopy(template)
            metric.update(
                {
                    "metric_id": metric_id,
                    "name": name,
                    "status": "OK",
                    "raw_value": str(max_pct),
                    "normalized_value": float(max_pct),
                    "unit": "%",
                    "error": None,
                }
            )
            metric["evidence"] = {
                "command": "df -hT" if "used_percent" in metric_id else "df -i",
                "output_summary": None,
                "raw_ref": f"raw/{metric_id}.out",
                "sampled_at": doc["collected_at"],
                "details": details,
            }
            return metric

        doc["metrics"] = [
            doc["metrics"][0],
            filesystem_metric(
                "local.filesystem.used_percent",
                "磁盘使用率",
                [
                    {"filesystem": "/dev/root", "mount": "/", "used_percent": 61, "status": "OK"},
                    {"filesystem": "/dev/data", "mount": "/data", "used_percent": 83, "status": "WARN"},
                ],
                83,
            ),
            filesystem_metric(
                "local.filesystem.inode_used_percent",
                "inode 使用率",
                [
                    {"filesystem": "/dev/root", "mount": "/", "used_percent": 1, "status": "OK"},
                    {"filesystem": "/dev/data", "mount": "/data", "used_percent": 2, "status": "OK"},
                ],
                2,
            ),
        ]
        out = render(doc)
        assert "[OK] 磁盘使用率: / 61.00 %" in out
        assert "[WARN] 磁盘使用率: /data 83.00 %" in out
        assert "[OK] inode 使用率: / 1.00 %" in out
        assert "[OK] inode 使用率: /data 2.00 %" in out
        assert "磁盘使用率: 83.00 %" not in out
        assert "inode 使用率: 2.00 %" not in out


    def test_legacy_filesystem_details_fall_back_to_metric_status(self):
        doc = valid_doc()
        metric = copy.deepcopy(doc["metrics"][0])
        metric.update({
            "metric_id": "local.filesystem.used_percent",
            "name": "磁盘使用率",
            "status": "CRIT",
            "raw_value": "91",
            "normalized_value": 91.0,
            "unit": "%",
            "error": None,
        })
        metric["evidence"] = {
            "command": "df -hT",
            "output_summary": None,
            "raw_ref": "raw/local.filesystem.used_percent.out",
            "sampled_at": doc["collected_at"],
            "details": [{"filesystem": "/dev/root", "mount": "/", "used_percent": 1}],
        }
        doc["metrics"] = [metric]
        out = render(doc)
        assert "[CRIT] 磁盘使用率: / 1.00 %" in out

    def test_unknown_metric_is_kept_in_problem_list_not_value_section(self):
        out = render(partial_doc())
        value_section, problem_section = out.split(
            "失败/未知指标列表（UNKNOWN/ERROR 显式原因，RR §2）", 1
        )
        assert "CPU 使用率" in value_section
        assert "systemd 服务状态" not in value_section
        assert "local.service.active" in problem_section


# --------------------------------------------------------------------------
# 2. UNKNOWN/ERROR 显式原因（REQ-R-02：missing/conflict/permission/timeout）
# --------------------------------------------------------------------------


class TestUnknownReasons:
    def test_reason_conflict(self):
        out = render(partial_doc())
        assert "原因=conflict" in out
        assert "C3" in out

    def test_reason_missing_business_and_error(self):
        out = render(partial_doc())
        assert "原因=missing" in out
        assert "COMMAND_NOT_FOUND" in out

    def test_reason_permission(self):
        out = render(partial_doc())
        assert "原因=permission" in out
        assert "PERMISSION_DENIED" in out

    def test_reason_timeout(self):
        out = render(partial_doc())
        assert "原因=timeout" in out
        assert "TIMEOUT" in out

    def test_reason_other_code_explicit(self):
        out = render(partial_doc())
        assert "原因=other:parse_failed" in out
        assert "PARSE_FAILED" in out

    def test_all_unknown_metrics_visible_none_hidden(self):
        doc = partial_doc()
        out = render(doc)
        body = out.split("失败/未知指标列表（UNKNOWN/ERROR 显式原因，RR §2）", 1)[1]
        for m in doc["metrics"]:
            if m["status"] == "UNKNOWN":
                assert m["metric_id"] in body
            else:
                assert m["metric_id"] not in body  # 非 UNKNOWN 不混入列表

    def test_error_host_detail_from_index(self):
        out = render(error_doc(), host_errors=host_errors())
        assert "CONNECTION_FAILED" in out
        assert "SSH 连接被拒绝" in out

    def test_classify_unknown_reason_unit(self):
        def mk(error_code=None, layer="unresolved-document-conflict", notes=""):
            return {
                "error": {"code": error_code} if error_code else None,
                "threshold": {"layer": layer, "notes": notes},
                "provenance": {"notes": None},
            }

        assert r.classify_unknown_reason(mk("PERMISSION_DENIED")) == "permission"
        assert r.classify_unknown_reason(mk("TIMEOUT")) == "timeout"
        assert r.classify_unknown_reason(mk("COMMAND_NOT_FOUND")) == "missing"
        assert r.classify_unknown_reason(mk("DATA_MISSING")) == "missing"
        assert r.classify_unknown_reason(mk("PARSE_FAILED")) == "other:parse_failed"
        assert r.classify_unknown_reason(mk("UNSUPPORTED_PROFILE")) == "other:unsupported_profile"
        assert r.classify_unknown_reason(mk(layer=None)) == "missing"
        assert r.classify_unknown_reason(mk(notes="文档冲突 C3 unresolved")) == "conflict"
        assert r.classify_unknown_reason(mk(notes="unit 名无配置/冲突 C8")) == "conflict"
        assert r.classify_unknown_reason(mk(notes="命中但关键词等级判定未解决（C10 冲突）")) == "conflict"
        assert r.classify_unknown_reason(mk(notes="持续>核数 → 缺失 → UNKNOWN")) == "missing"
        assert r.classify_unknown_reason(mk(notes="10–20% 区间 C4")) == "missing"
        assert r.classify_unknown_reason(mk(notes="≥80% → 缺失 C5 → UNKNOWN")) == "missing"
        assert r.classify_unknown_reason(mk(notes="端口/模式无配置（C13）")) == "missing"
        assert r.classify_unknown_reason(mk(notes="")) == "missing"


# --------------------------------------------------------------------------
# 3. HR §8：execution_status != SUCCESS → 技术失败计数显式展示不掩盖
# --------------------------------------------------------------------------


class TestTechnicalFailureVisible:
    def test_partial_run_shows_failed_counts(self):
        out = render(partial_doc())
        assert "executed=5 failed=4" in out
        assert "技术失败" in out
        assert "HR §8" in out

    def test_error_run_mentions_no_business_conclusion_hosts(self):
        out = render(valid_doc(), error_doc(), host_errors=host_errors())
        assert "无业务结论主机 1 台" in out
        assert "failed=3" in out

    def test_success_run_no_failure_marker(self):
        out = render(valid_doc())
        assert "HR §8" not in out  # SUCCESS 主机不标注技术失败
        assert "executed=1 failed=0" in out


# --------------------------------------------------------------------------
# 4. 颜色与无颜色符号（REQ-R-07；NO_COLOR/TERM=dumb/非 TTY → 符号/缩写）
# --------------------------------------------------------------------------


class TestColorAndSymbols:
    def test_no_color_by_default_nontty(self):
        # pytest 捕获的 stdout 非 TTY → 默认无 ANSI 颜色
        assert r.color_enabled() is False
        out = render(partial_doc())
        assert "\x1b[" not in out

    def test_no_color_env(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert r.color_enabled() is False
        out = render(partial_doc())
        assert "\x1b[" not in out

    def test_terminfo_dumb(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "dumb")
        assert r.color_enabled() is False

    def test_force_color_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert r.color_enabled(force=True) is True
        # 徽标颜色直接断言（RR §5 四状态 + execution_status）
        assert r.badge("OK", color=True) == "\x1b[32m[OK]\x1b[0m"
        assert r.badge("WARN", color=True) == "\x1b[33m[WARN]\x1b[0m"
        assert r.badge("CRIT", color=True) == "\x1b[31m[CRIT]\x1b[0m"
        assert r.badge("UNKNOWN", color=True) == "\x1b[90m[UNKN]\x1b[0m"
        # 报告整体输出含彩色徽标（列表内 UNKNOWN 徽标 + 主机摘要执行徽标）
        out = r.render_report([partial_doc()], color=True)
        assert "\x1b[90m[UNKN]\x1b[0m" in out

    def test_execution_badge_color_bold(self):
        assert r.execution_badge("SUCCESS", color=True) == "\x1b[1m\x1b[32m[SUCCESS]\x1b[0m"
        assert r.execution_badge("PARTIAL", color=True) == "\x1b[1m\x1b[33m[PARTIAL]\x1b[0m"
        assert r.execution_badge("ERROR", color=True) == "\x1b[1m\x1b[31m[ERROR]\x1b[0m"

    def test_no_color_symbols_and_abbreviations(self):
        # 无颜色环境：徽标 = 文本缩写（[OK]/[WARN]/[CRIT]/[UNKN]），不依赖颜色
        assert r.badge("OK", color=False) == "[OK]"
        assert r.badge("WARN", color=False) == "[WARN]"
        assert r.badge("CRIT", color=False) == "[CRIT]"
        assert r.badge("UNKNOWN", color=False) == "[UNKN]"
        out = render(partial_doc())
        assert "[UNKN]" in out
        assert "? [UNKN]" in out   # 业务 UNKNOWN 符号前缀
        assert "! [UNKN]" in out   # error 指标符号前缀
        assert "[PARTIAL]" in out  # execution_status 徽标缩写
        # execution_status 徽标同样不依赖颜色
        out3 = render(valid_doc(), partial_doc(), error_doc(), host_errors=host_errors())
        assert "[SUCCESS]" in out3 and "[PARTIAL]" in out3 and "[ERROR]" in out3


# --------------------------------------------------------------------------
# 5. 渲染零采集（REQ-N-06：mock 断言零采集调用 + 导入边界）
# --------------------------------------------------------------------------


class TestZeroCollection:
    def test_render_report_zero_collection(self, monkeypatch):
        from inspect import ansible_runner

        run_mock = mock.Mock()
        sub_mock = mock.Mock()
        monkeypatch.setattr(ansible_runner, "run", run_mock)
        monkeypatch.setattr(subprocess, "run", sub_mock)
        out = render(partial_doc(), host_errors=host_errors())
        assert "node-fx02" in out
        run_mock.assert_not_called()
        sub_mock.assert_not_called()

    def test_render_inspection_report_zero_collection(self, tmp_path, monkeypatch):
        from inspect import ansible_runner

        docs = [valid_doc(), partial_doc(), error_doc()]
        fs.write_inspection(
            tmp_path, RUN_ID, INSPECTION_ID, docs, host_errors=host_errors()
        )
        run_mock = mock.Mock()
        sub_mock = mock.Mock()
        monkeypatch.setattr(ansible_runner, "run", run_mock)
        monkeypatch.setattr(subprocess, "run", sub_mock)
        out = r.render_inspection_report(tmp_path, INSPECTION_ID, color=False)
        assert "node-fx02" in out and "node-fx03" in out
        run_mock.assert_not_called()
        sub_mock.assert_not_called()

    def test_renderer_source_imports_no_collection_modules(self):
        src = Path(r.__file__).read_text(encoding="utf-8")
        imports = [
            ln.strip()
            for ln in src.splitlines()
            if re.match(r"^(?:import|from)\s", ln.strip())
        ]
        assert imports, "模块应存在 import 语句"
        for ln in imports:
            assert "subprocess" not in ln
            assert "ansible_runner" not in ln
            assert "probe" not in ln


# --------------------------------------------------------------------------
# 6. 退出码说明（cli-contract §4）
# --------------------------------------------------------------------------


class TestExitCodeNote:
    def test_exit_code_note_present(self):
        out = render(valid_doc())
        assert "退出码说明（cli-contract §4）" in out
        assert "0   成功" in out
        assert "2   用法错误" in out
        assert "10  执行失败" in out
        assert "20  业务告警" in out


# --------------------------------------------------------------------------
# 7. 事实源目录渲染与防御（TD §3 布局，只读）
# --------------------------------------------------------------------------


class TestInspectionReportFile:
    def test_render_inspection_report_matches_memory(self, tmp_path):
        docs = [valid_doc(), partial_doc(), error_doc()]
        fs.write_inspection(
            tmp_path, RUN_ID, INSPECTION_ID, docs, host_errors=host_errors()
        )
        out = r.render_inspection_report(tmp_path, INSPECTION_ID, color=False)
        expected = r.render_report(docs, host_errors=host_errors(), color=False)
        assert out == expected  # 同一份 JSON，内存与文件渲染一致（RR §6.1）
        assert "CONNECTION_FAILED" in out

    def test_render_inspection_report_corrupt_json(self, tmp_path):
        insp = tmp_path / "insp-corrupt"
        hosts_dir = insp / "hosts"
        hosts_dir.mkdir(parents=True)
        (hosts_dir / "node-x.json").write_text(
            '{"schema": "host-result-v1", "schema_version": 1, "inspection_id":',
            encoding="utf-8",
        )
        index = {
            "schema": "inspection-index-v1",
            "version": 1,
            "run_id": RUN_ID,
            "inspection_id": "insp-corrupt",
            "generated_at": "2026-08-14T12:00:00+08:00",
            "hosts": [
                {
                    "host": "node-x",
                    "file": str(hosts_dir / "node-x.json"),
                    "sha256": "deadbeef",
                    "execution_status": "ERROR",
                    "error": None,
                }
            ],
        }
        (insp / "inspection-insp-corrupt-index.json").write_text(
            json.dumps(index), encoding="utf-8"
        )
        with pytest.raises(fs.FactSourceError):
            r.render_inspection_report(tmp_path, "insp-corrupt")

    def test_empty_docs_renders_explicitly(self):
        out = render()
        assert "无主机文档" in out
        assert "（无 UNKNOWN/ERROR 指标）" in out
        assert "退出码说明（cli-contract §4）" in out
