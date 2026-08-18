"""tests/test_normalize.py — T-104 normalize 层测试（合同 AC-1）。

覆盖（合同必需步骤 5 + mitigations）：
  - 10 个 P0 指标解析器（tests/fixtures/raw/ 预录输出为解析输入基准）；
  - 脱敏（IP→<IP>、凭据零出现）解析级与文档级（REQ-E-09）；
  - 四状态判定（HR §4 不可变顺序：error → 外部配置 → 文档基线 →
    缺失/冲突 → UNKNOWN；C3/C5/C8/C10/C13 边界）；
  - threshold/provenance 填充与可追溯（REQ-D-04，test_threshold_traceability）；
  - 外部配置覆盖生效（TD §6.2 首个匹配）与未命中回退；
  - 执行/业务状态分离（error → status=UNKNOWN，技术失败不伪装 CRIT）；
  - 与 T-103 fixture 模式端到端管道（node-a/b/c/d/e）；
  - inspection_id 格式、meta、必填字段、解析器注册表对齐；
  - T-104F：IP/含凭据关键字 host 键 → inspection_id 安全映射后合法且可
    落盘（validate 闸门 + 真实写入），业务字段脱敏不受影响；
  - validate_host_result（内嵌 schema 语义子集）正反例。

只读使用 tests/fixtures/raw/（T-103 交付，禁止修改）；不连接、不执行命令。
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from inspect import ansible_runner as ar
from inspect import config as config_mod
from inspect import fact_source as fs
from inspect import metrics as metrics_mod
from inspect import normalize as n

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "raw"
RUN_ID = "run-20260814-001"
COLLECTED = "2026-08-15T10:30:00+08:00"

# TD §6.3 风格单产品 profile（elasticsearch；值符合 ansible_runner 安全字符集）
PROFILE = {
    "process_pattern": "org.elasticsearch.bootstrap.Elasticsearch",
    "unit": "elasticsearch",
    "ports": [9200, 9300],
    "fs_paths": ["/", "/data"],
    "log_paths": ["/var/log/elasticsearch/*.log"],
    "log_keywords": ["ERROR", "FATAL"],
}


def raw(host: str, metric_id: str) -> str:
    """读取 T-103 预录原始输出（解析输入基准，只读）。"""
    return (FIXTURE_DIR / host / f"{metric_id}.out").read_text(encoding="utf-8")


def resolved_baseline():
    return config_mod.build_resolved_thresholds()


def override_resolved(metrics: dict, source: str = "<test-override>") -> dict:
    return config_mod.build_resolved_thresholds(
        override={
            "schema": "threshold-override-v1",
            "version": 1,
            "scope": None,
            "hosts": None,
            "metrics": metrics,
        },
        override_source=source,
    )


def metric_result(metric_id: str, stdout: str = "", *, rc: int = 0, stderr: str = "", error=None) -> dict:
    return {
        "metric_id": metric_id,
        "rc": rc,
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
    }


def host_result(
    host: str,
    metrics: list,
    *,
    ip: str = "192.168.1.7",
    probe_status: str = "ok",
    host_error=None,
    execution_status: str = None,
) -> dict:
    if execution_status is None:
        execution_status = "SUCCESS" if all(m["error"] is None for m in metrics) else "PARTIAL"
    failed = sum(1 for m in metrics if m["error"] is not None)
    return {
        "host": host,
        "ip": ip,
        "probe": {},
        "probe_status": probe_status,
        "host_error": host_error,
        "execution_status": execution_status,
        "metrics": list(metrics),
        "summary": {
            "total": len(metrics),
            "executed": len(metrics) - failed,
            "failed": failed,
        },
        "duration_sec": 3.2,
    }


def normalize_one(
    metric_id: str,
    stdout: str = "",
    *,
    stderr: str = "",
    rc: int = 0,
    error=None,
    profile=None,
    resolved=None,
    host: str = "node-test",
    execution_status: str = None,
) -> dict:
    hr = host_result(
        host,
        [metric_result(metric_id, stdout, rc=rc, stderr=stderr, error=error)],
        execution_status=execution_status,
    )
    doc = n.normalize_host_result(
        hr,
        run_id=RUN_ID,
        collected_at=COLLECTED,
        profile=profile,
        resolved_thresholds=resolved if resolved is not None else resolved_baseline(),
    )
    return doc["metrics"][0]


def doc_json_text(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False)


# --------------------------------------------------------------------------
# 1. 解析器（10 指标，fixtures/raw/ 预录输出为基准）
# --------------------------------------------------------------------------


class TestParsers:
    def test_parse_process_present(self):
        parsed = n.parse_process_present(raw("node-a", "local.process.present"))
        assert parsed["present"] is True
        assert parsed["count"] == 2
        assert len(parsed["summary"]) == 2

    def test_parse_process_present_absent(self):
        parsed = n.parse_process_present("")
        assert parsed["present"] is False
        assert parsed["count"] == 0

    def test_parse_service_active(self):
        parsed = n.parse_service_active(raw("node-a", "local.service.active"))
        assert parsed["active_state"] == "active"
        assert parsed["substate"] == "running"

    def test_parse_service_active_is_active_only(self):
        parsed = n.parse_service_active("active\n")
        assert parsed["active_state"] == "active"

    def test_parse_service_active_empty_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_service_active("")

    def test_parse_port_listening(self):
        parsed = n.parse_port_listening(raw("node-a", "local.port.listening"))
        assert parsed["ports"] == [5601, 9200, 9300]  # sorted 数值序
        assert parsed["listeners"] == ["java", "node"]
        rows_text = "\n".join(r["line"] for r in parsed["rows"])
        assert "<IP>" in rows_text  # 监听地址脱敏
        assert not n.contains_plain_ip(rows_text)

    def test_parse_port_listening_no_listen_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_port_listening("State Recv-Q Send-Q Local Address:Port Peer Address:Port\n")

    def test_parse_cpu_utilization(self):
        parsed = n.parse_cpu_utilization(raw("node-a", "local.cpu.utilization"))
        assert parsed["us"] == 2.5
        assert parsed["sy"] == 0.8
        assert parsed["total"] == 3.3

    def test_parse_cpu_utilization_no_cpu_line_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_cpu_utilization("Tasks: 210 total\n")

    def test_parse_cpu_load_1m(self):
        parsed = n.parse_cpu_load_1m(raw("node-a", "local.cpu.load_1m"))
        assert parsed["load_1m"] == 0.52
        assert parsed["load_15m"] == 0.39
        assert parsed["nproc"] == 8

    def test_parse_cpu_load_1m_garbage_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_cpu_load_1m("not-a-load\n")

    def test_parse_memory_available_percent(self):
        parsed = n.parse_memory_available_percent(raw("node-a", "local.memory.available_percent"))
        assert parsed["total"] == 31969
        assert parsed["available"] == 26351
        assert parsed["pct"] == 82

    def test_parse_memory_available_percent_missing_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_memory_available_percent("Swap: 8191 0 8191\n")

    def test_parse_swap_used_percent(self):
        parsed = n.parse_swap_used_percent(raw("node-a", "local.swap.used_percent"))
        assert parsed["used"] == 0
        assert parsed["configured"] is True
        assert parsed["pct"] == 0

    def test_parse_swap_used_percent_unconfigured(self):
        parsed = n.parse_swap_used_percent("Mem: 1000 100 900 0 0 900\n")
        assert parsed["configured"] is False
        assert parsed["used"] == 0

    def test_parse_filesystem_used_percent(self):
        parsed = n.parse_filesystem_used_percent(raw("node-a", "local.filesystem.used_percent"))
        assert parsed["max_pct"] == 91
        assert len(parsed["rows"]) == 2
        assert [row["mount"] for row in parsed["rows"]] == ["/", "/data"]
        assert [row["pct"] for row in parsed["rows"]] == [66, 91]

    def test_parse_filesystem_used_percent_empty_raises(self):
        with pytest.raises(n.ParseError):
            n.parse_filesystem_used_percent("Filesystem Type Size Used Avail Use% Mounted on\n")

    def test_parse_filesystem_inode_used_percent(self):
        parsed = n.parse_filesystem_inode_used_percent(
            raw("node-a", "local.filesystem.inode_used_percent")
        )
        assert parsed["max_pct"] == 1
        assert len(parsed["rows"]) == 2
        assert [row["mount"] for row in parsed["rows"]] == ["/", "/data"]

    def test_parse_logs_key_evidence(self):
        parsed = n.parse_logs_key_evidence(raw("node-a", "local.logs.key_evidence"))
        assert parsed["hit_count"] == 3
        assert parsed["keyword_counts"]["ERROR"] == 2
        assert parsed["keyword_counts"]["WARN"] == 1

    def test_parse_logs_key_evidence_empty(self):
        parsed = n.parse_logs_key_evidence("")
        assert parsed["hit_count"] == 0


# --------------------------------------------------------------------------
# 2. 脱敏（REQ-E-09：IP→<IP>、凭据零出现，测试可验证）
# --------------------------------------------------------------------------


class TestMasking:
    def test_mask_ipv4(self):
        assert n.mask_ip("192.168.1.1:9200") == "<IP>:9200"
        assert n.mask_ip("0.0.0.0") == "<IP>"
        assert n.mask_ip("10.1.2.3 192.168.5.10") == "<IP> <IP>"

    def test_mask_ipv6(self):
        assert n.mask_ip("fe80::1") == "<IP>"
        assert n.mask_ip("::1") == "<IP>"
        assert n.mask_ip("2001:db8::ff00:42:8329") == "<IP>"

    def test_mask_does_not_touch_timestamps(self):
        # 时间戳（非 IPv6：无 :: 且不足 8 组）与版本号不被误判
        assert n.mask_ip("2026-08-15T09:59:32+08:00") == "2026-08-15T09:59:32+08:00"
        assert n.mask_ip("10:00:01") == "10:00:01"

    def test_mask_credentials(self):
        # 键值构造整体替换（键名也不残留 → 零出现断言可验证）
        assert n.mask_credentials("password=secret123") == "<REDACTED>"
        assert n.mask_credentials("PASSWORD: xyz") == "<REDACTED>"
        assert n.mask_credentials("token=abc.def") == "<REDACTED>"
        assert n.mask_credentials("api_key=1234") == "<REDACTED>"

    def test_mask_credentials_url_userinfo(self):
        assert n.mask_credentials("https://admin:pass@es.internal:9200") == (
            "https://<REDACTED>@es.internal:9200"
        )

    def test_mask_credentials_cli_flags(self):
        assert n.mask_credentials("-p secret") == "<REDACTED>"
        assert n.mask_credentials("--user admin") == "<REDACTED>"
        assert n.mask_credentials("-u=admin") == "<REDACTED>"
        assert n.mask_credentials("a --password x b") == "a <REDACTED> b"

    def test_mask_credentials_jvm_props(self):
        assert n.mask_credentials("-Dpassword=Abc123!") == "<REDACTED>"
        assert n.mask_credentials("-Des.path.home=/opt/es") == "-Des.path.home=/opt/es"

    def test_mask_credentials_bare_keyword(self):
        # 裸凭据关键字兜底（零出现保证）
        assert n.mask_credentials("authentication failed: secret") == (
            "authentication failed: <REDACTED>"
        )

    def test_mask_output_idempotent(self):
        text = "192.168.1.1 password=abc http://u:p@h/"
        assert n.mask_output(n.mask_output(text)) == n.mask_output(text)

    def test_contains_helpers(self):
        assert n.contains_plain_ip("ip 192.168.1.1")
        assert not n.contains_plain_ip("ip <IP>")
        assert n.contains_credential("pwd=1")
        assert not n.contains_credential("nothing here")

    def test_desensitization_host_ip(self):
        doc = n.normalize_host_result(
            host_result("node-a", [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert doc["host"]["ip"] == "<IP>"
        assert not n.contains_plain_ip(doc_json_text(doc))

    def test_desensitization_adversarial_output(self):
        # 解析器漏脱敏的兜底：文档级强制扫描（防御式最终保证）
        evil = "4321 java 192.168.5.10:3306 -Dpassword=Admin@123 https://u:p@h/secret"
        doc = n.normalize_host_result(
            host_result(
                "node-test",
                [metric_result("local.process.present", evil, error=None)],
            ),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        text = doc_json_text(doc)
        assert "<IP>" in text
        assert "<REDACTED>" in text
        assert not n.contains_plain_ip(text)
        assert not n.contains_credential(text)

    def test_desensitization_node_a_document(self):
        doc = n.normalize_host_result(
            host_result("node-a", [metric_result(m, raw("node-a", m)) for m in metrics_mod.ALL_METRIC_IDS]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        text = doc_json_text(doc)
        assert not n.contains_plain_ip(text)
        assert not n.contains_credential(text)


# --------------------------------------------------------------------------
# 3. 四状态判定（HR §4；边界数值来自 MR §5/§6 已批准基线）
# --------------------------------------------------------------------------


class TestJudgment:
    def test_judge_process_present_ok(self):
        metric = normalize_one("local.process.present", raw("node-a", "local.process.present"))
        assert metric["status"] == "OK"

    def test_judge_process_present_crit_absent(self):
        metric = normalize_one("local.process.present", "")
        assert metric["status"] == "CRIT"

    def test_judge_service_active_ok(self):
        metric = normalize_one("local.service.active", raw("node-a", "local.service.active"))
        assert metric["status"] == "OK"

    def test_judge_service_active_crit_inactive(self):
        metric = normalize_one("local.service.active", "inactive\nActiveState=inactive\nSubState=dead\n")
        assert metric["status"] == "CRIT"

    def test_judge_port_warn_extra(self):
        # node-a 监听 [9200,9300,5601]；profile [9200,9300] → 5601 模式外（C7）
        metric = normalize_one("local.port.listening", raw("node-a", "local.port.listening"), profile=PROFILE)
        assert metric["status"] == "WARN"
        assert "C7" in (metric["threshold"]["notes"] or "")

    def test_judge_port_ok(self):
        profile = dict(PROFILE, ports=[9200, 9300, 5601])
        metric = normalize_one("local.port.listening", raw("node-a", "local.port.listening"), profile=profile)
        assert metric["status"] == "OK"

    def test_judge_port_crit_missing(self):
        profile = dict(PROFILE, ports=[9200, 9999])
        metric = normalize_one("local.port.listening", raw("node-a", "local.port.listening"), profile=profile)
        assert metric["status"] == "CRIT"

    def test_judge_port_unknown_no_profile(self):
        # C13：端口/模式无配置 → UNKNOWN（不静默跳过）
        metric = normalize_one("local.port.listening", raw("node-a", "local.port.listening"))
        assert metric["status"] == "UNKNOWN"
        assert metric["threshold"]["layer"] == n.LAYER_UNRESOLVED

    def test_judge_cpu_ok(self):
        metric = normalize_one("local.cpu.utilization", raw("node-a", "local.cpu.utilization"))
        assert metric["status"] == "OK"
        assert metric["normalized_value"] == 3.3

    def test_judge_cpu_ok_70_80_with_note(self):
        out = "%Cpu(s): 72.0 us, 3.0 sy, 0.0 ni, 25.0 id, 0.0 wa, 0.0 hi, 0.0 si, 0.0 st\n"
        metric = normalize_one("local.cpu.utilization", out)
        assert metric["status"] == "OK"
        assert "单次采样" in (metric["threshold"]["notes"] or "")

    def test_judge_cpu_warn_80_90(self):
        out = "%Cpu(s): 82.0 us, 3.0 sy, 0.0 ni, 15.0 id, 0.0 wa, 0.0 hi, 0.0 si, 0.0 st\n"
        metric = normalize_one("local.cpu.utilization", out)
        assert metric["status"] == "WARN"
        assert metric["threshold"]["rule_id"].endswith(".warn")

    def test_judge_cpu_over90_stays_warn_with_note(self):
        # TD §5.2：>90% 无业务证据采集能力 → 保持 WARN 并 provenance 注明
        out = (
            "%Cpu(s): 92.0 us, 3.0 sy, 0.0 ni, 5.0 id, 0.0 wa, 0.0 hi, 0.0 si, 0.0 st\n"
            "PID COMMAND %CPU %MEM\n4321 java 92.0 30.0\n"
        )
        metric = normalize_one("local.cpu.utilization", out)
        assert metric["status"] == "WARN"
        assert "CRIT" in (metric["threshold"]["notes"] or "")

    def test_judge_load_ok(self):
        metric = normalize_one("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))
        assert metric["status"] == "OK"

    def test_load_fact_contains_all_windows_and_judgements(self):
        metric = normalize_one("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))
        details = metric["evidence"]["details"]
        assert [d["window"] for d in details] == ["1 分钟", "5 分钟", "15 分钟"]
        assert [d["load"] for d in details] == [0.52, 0.44, 0.39]
        assert all(d["cpu_cores"] == 8 for d in details)
        assert all(d["status"] == "OK" for d in details)
        assert all(d["judgement"] == "负载 <= CPU 核数：正常" for d in details)
        doc = n.normalize_host_result(
            host_result("node-a", [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        n.validate_host_result(doc)

    def test_judge_load_unknown_over_nproc(self):
        # 持续>核数 → 告警等级缺失（基线 UNKNOWN 注记）→ UNKNOWN
        metric = normalize_one("local.cpu.load_1m", "9.5 9.1 8.9 1/210 12345\n8\n")
        assert metric["status"] == "UNKNOWN"
        assert "核数" in (metric["threshold"]["notes"] or "")

    def test_judge_load_unknown_no_nproc(self):
        metric = normalize_one("local.cpu.load_1m", "9.5 9.1 8.9 1/210 12345\n")
        assert metric["status"] == "UNKNOWN"

    def test_judge_memory_ok(self):
        metric = normalize_one("local.memory.available_percent", raw("node-a", "local.memory.available_percent"))
        assert metric["status"] == "OK"
        assert metric["normalized_value"] == 82.0

    def test_judge_memory_crit_below10(self):
        metric = normalize_one("local.memory.available_percent", "Mem: 1000 0 0 0 0 80\n")
        assert metric["status"] == "CRIT"

    def test_judge_memory_unknown_10_20(self):
        # C4：10–20% 区间文档未定义 → UNKNOWN
        metric = normalize_one("local.memory.available_percent", "Mem: 1000 0 0 0 0 150\n")
        assert metric["status"] == "UNKNOWN"
        assert "C4" in (metric["threshold"]["notes"] or "")

    def test_judge_swap_ok_zero(self):
        metric = normalize_one("local.swap.used_percent", raw("node-a", "local.swap.used_percent"))
        assert metric["status"] == "OK"

    def test_judge_swap_unknown_used_positive(self):
        # C3：used>0 冲突未解决 → UNKNOWN
        metric = normalize_one("local.swap.used_percent", "Swap: 8191 512 7679\n")
        assert metric["status"] == "UNKNOWN"
        assert "C3" in (metric["threshold"]["notes"] or "")

    def test_judge_fs_ok(self):
        out = "/dev/sda1 ext4 100G 62G 33G 66% /\n"
        metric = normalize_one("local.filesystem.used_percent", out)
        assert metric["status"] == "OK"

    def test_judge_fs_warn_75_85(self):
        out = "/dev/sda1 ext4 100G 62G 33G 80% /\n"
        metric = normalize_one("local.filesystem.used_percent", out)
        assert metric["status"] == "WARN"

    def test_judge_fs_crit_over85(self):
        metric = normalize_one("local.filesystem.used_percent", raw("node-a", "local.filesystem.used_percent"))
        assert metric["status"] == "CRIT"
        assert metric["normalized_value"] == 91.0

    def test_judge_fs_crit_over95_fault_note(self):
        out = "/dev/sda1 ext4 100G 96G 4G 96% /\n"
        metric = normalize_one("local.filesystem.used_percent", out)
        assert metric["status"] == "CRIT"
        assert "95%" in (metric["threshold"]["notes"] or "")

    def test_judge_inode_ok(self):
        metric = normalize_one(
            "local.filesystem.inode_used_percent", raw("node-a", "local.filesystem.inode_used_percent")
        )
        assert metric["status"] == "OK"

    def test_judge_inode_unknown_over80(self):
        # C5：≥80% 数值边界缺失 → UNKNOWN
        metric = normalize_one("local.filesystem.inode_used_percent", "/dev/sda1 6553600 5570560 983040 85% /\n")
        assert metric["status"] == "UNKNOWN"
        assert "C5" in (metric["threshold"]["notes"] or "")

    def test_judge_logs_ok_no_hits(self):
        metric = normalize_one("local.logs.key_evidence", "")
        assert metric["status"] == "OK"

    def test_judge_logs_unknown_hits(self):
        # C10：命中但关键词等级判定未解决 → UNKNOWN
        metric = normalize_one("local.logs.key_evidence", raw("node-a", "local.logs.key_evidence"))
        assert metric["status"] == "UNKNOWN"
        assert metric["normalized_value"] == 3.0


# --------------------------------------------------------------------------
# 4. threshold/provenance 填充与可追溯（REQ-D-04）
# --------------------------------------------------------------------------


class TestThresholdTraceability:
    def test_threshold_document_baseline(self):
        baseline = resolved_baseline()
        metric = normalize_one("local.cpu.utilization", raw("node-a", "local.cpu.utilization"))
        t = metric["threshold"]
        assert t["layer"] == n.LAYER_DOCUMENT_BASELINE
        assert t["rule_id"] == "linux-common-p0-v1.cpu.utilization.ok"
        baseline_rule = next(
            r for r in baseline["local.cpu.utilization"]["rules"] if r["status"] == "OK"
        )
        assert t["value"] == baseline_rule["rule"]
        assert t["source_anchor"] == baseline["local.cpu.utilization"]["provenance"]["doc_sources"][0]
        assert metric["provenance"]["doc_sources"] == [t["source_anchor"]]

    def test_threshold_unresolved_conflict(self):
        metric = normalize_one("local.swap.used_percent", "Swap: 8191 512 7679\n")
        t = metric["threshold"]
        assert t["layer"] == n.LAYER_UNRESOLVED
        assert t["rule_id"] is None
        assert t["value"] is None
        assert t["source_anchor"] == resolved_baseline()["local.swap.used_percent"]["provenance"]["doc_sources"][0]
        assert "C3" in (t["notes"] or "")
        assert metric["provenance"]["notes"] == t["notes"]

    def test_threshold_error_all_null(self):
        # HR §7 示例：error 指标 threshold 全 null
        error = {"code": n.ERROR_PERMISSION_DENIED, "message": "permission denied", "metric_status": "UNKNOWN"}
        metric = normalize_one("local.logs.key_evidence", "", error=error)
        assert metric["status"] == "UNKNOWN"
        assert metric["threshold"] == {
            "layer": None,
            "rule_id": None,
            "value": None,
            "source_anchor": None,
            "notes": None,
        }
        assert metric["error"]["code"] == n.ERROR_PERMISSION_DENIED
        assert metric["error"]["metric_status"] == "UNKNOWN"

    def test_raw_and_normalized_values(self):
        metric = normalize_one("local.filesystem.used_percent", raw("node-a", "local.filesystem.used_percent"))
        assert metric["raw_value"] == "91"
        assert metric["normalized_value"] == 91.0
        assert metric["unit"] == "%"

    def test_evidence_fields(self):
        metric = normalize_one("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))
        ev = metric["evidence"]
        assert ev["raw_ref"] == "raw/local.cpu.load_1m.out"
        assert ev["sampled_at"] == COLLECTED
        assert "load_1m=0.52" in ev["output_summary"]


# --------------------------------------------------------------------------
# 5. 外部配置覆盖（TD §6.2 首个匹配生效）与判定顺序（HR §4）
# --------------------------------------------------------------------------


class TestExternalConfig:
    def test_external_override_applies(self):
        resolved = override_resolved(
            {
                "local.memory.available_percent": {
                    "rules": [
                        {"status": "WARN", "range": [10, 20], "note": "测试：10-20 → WARN"},
                        {"status": "CRIT", "op": "<", "value": 10, "note": "测试：<10 → CRIT"},
                    ]
                }
            }
        )
        metric = normalize_one(
            "local.memory.available_percent", "Mem: 1000 0 0 0 0 150\n", resolved=resolved
        )
        assert metric["status"] == "WARN"
        assert metric["threshold"]["layer"] == n.LAYER_EXTERNAL_CONFIG
        assert metric["threshold"]["value"] == "[10.0,20.0]"  # 规则数值按 float 归一
        assert metric["threshold"]["source_anchor"] == "<test-override>"
        assert metric["provenance"]["config_sources"] == ["<test-override>"]
        assert metric["threshold"]["notes"] == "测试：10-20 → WARN"

    def test_external_override_op_rule(self):
        resolved = override_resolved(
            {"local.memory.available_percent": {"rules": [{"status": "CRIT", "op": "<", "value": 10, "note": "n"}]}}
        )
        metric = normalize_one(
            "local.memory.available_percent", "Mem: 1000 0 0 0 0 80\n", resolved=resolved
        )
        assert metric["status"] == "CRIT"
        assert metric["threshold"]["value"] == "<10.0"

    def test_external_override_first_match_wins(self):
        resolved = override_resolved(
            {
                "local.cpu.utilization": {
                    "rules": [
                        {"status": "WARN", "range": [0, 50], "note": "先命中"},
                        {"status": "CRIT", "range": [0, 100], "note": "后命中"},
                    ]
                }
            }
        )
        out = "%Cpu(s): 30.0 us, 0.0 sy, 0.0 ni, 70.0 id, 0.0 wa, 0.0 hi, 0.0 si, 0.0 st\n"
        metric = normalize_one("local.cpu.utilization", out, resolved=resolved)
        assert metric["status"] == "WARN"
        assert metric["threshold"]["notes"] == "先命中"

    def test_external_override_no_match_falls_back_to_baseline(self):
        resolved = override_resolved(
            {"local.memory.available_percent": {"rules": [{"status": "WARN", "range": [10, 20], "note": "n"}]}}
        )
        metric = normalize_one(
            "local.memory.available_percent", raw("node-a", "local.memory.available_percent"), resolved=resolved
        )
        assert metric["status"] == "OK"  # 82 未命中 [10,20] → 回退文档基线
        assert metric["threshold"]["layer"] == n.LAYER_DOCUMENT_BASELINE
        assert "回退" in (metric["provenance"]["notes"] or "")

    def test_external_override_non_numeric_metric_falls_back(self):
        # 非数值指标无法应用数值规则 → 回退基线判定（不抛异常、不误判）
        resolved = override_resolved(
            {"local.process.present": {"rules": [{"status": "WARN", "op": ">", "value": 0, "note": "n"}]}}
        )
        metric = normalize_one("local.process.present", raw("node-a", "local.process.present"), resolved=resolved)
        assert metric["status"] == "OK"
        assert metric["threshold"]["layer"] == n.LAYER_DOCUMENT_BASELINE

    def test_decision_order_error_beats_override(self):
        # HR §4 步骤 1：error 存在 → UNKNOWN，不参与业务判定（外部配置也不覆盖）
        resolved = override_resolved(
            {"local.memory.available_percent": {"rules": [{"status": "WARN", "range": [10, 20], "note": "n"}]}}
        )
        error = {"code": n.ERROR_TIMEOUT, "message": "超时", "metric_status": "UNKNOWN"}
        metric = normalize_one(
            "local.memory.available_percent", "Mem: 1000 0 0 0 0 150\n", error=error, resolved=resolved
        )
        assert metric["status"] == "UNKNOWN"
        assert metric["error"]["code"] == n.ERROR_TIMEOUT
        assert metric["threshold"]["layer"] is None


# --------------------------------------------------------------------------
# 6. 技术失败语义（执行/业务分离；error → UNKNOWN）
# --------------------------------------------------------------------------


class TestErrorSemantics:
    @pytest.mark.parametrize(
        "code,message",
        [
            (n.ERROR_CONNECTION_FAILED, "连接失败"),
            (n.ERROR_TIMEOUT, "命令超时"),
            (n.ERROR_PERMISSION_DENIED, "权限不足"),
            (n.ERROR_COMMAND_NOT_FOUND, "命令缺失"),
            (n.ERROR_DATA_MISSING, "数据缺失"),
            (n.ERROR_PROBE_FAILED, "探测失败"),
            (n.ERROR_UNSUPPORTED_PROFILE, "无 profile"),
        ],
    )
    def test_error_codes_map_to_unknown(self, code, message):
        error = {"code": code, "message": message, "metric_status": "UNKNOWN"}
        metric = normalize_one("local.cpu.load_1m", "", error=error)
        assert metric["status"] == "UNKNOWN"
        assert metric["error"]["code"] == code
        assert metric["error"]["metric_status"] == "UNKNOWN"
        assert metric["normalized_value"] is None

    def test_parse_failed(self):
        metric = normalize_one("local.port.listening", "State Recv-Q Send-Q Local Address:Port\n")
        assert metric["status"] == "UNKNOWN"
        assert metric["error"]["code"] == n.ERROR_PARSE_FAILED
        assert "解析失败" in metric["error"]["message"]

    def test_unknown_metric_id_defensive(self):
        hr = host_result("node-test", [metric_result("local.foo.bar", "x")])
        doc = n.normalize_host_result(hr, run_id=RUN_ID, collected_at=COLLECTED)
        metric = doc["metrics"][0]
        assert metric["status"] == "UNKNOWN"
        assert metric["error"]["code"] == n.ERROR_PARSE_FAILED
        assert "无该指标解析器" in metric["error"]["message"]

    def test_error_host_connection_failed(self):
        hr = host_result(
            "node-c",
            [],
            host_error={"code": n.ERROR_CONNECTION_FAILED, "message": "连接失败", "metric_status": "UNKNOWN"},
            probe_status="failed",
            execution_status="ERROR",
        )
        doc = n.normalize_host_result(hr, run_id=RUN_ID, collected_at=COLLECTED)
        assert doc["execution_status"] == "ERROR"
        assert doc["metrics"] == []
        assert doc["execution_summary"] == {
            "total_metrics": 0,
            "ok": 0,
            "warn": 0,
            "crit": 0,
            "unknown": 0,
            "executed": 0,
            "failed": 0,
        }

    def test_error_host_probe_failed(self):
        hr = host_result(
            "node-d",
            [],
            probe_status="failed",
            execution_status="ERROR",
            host_error={"code": n.ERROR_PROBE_FAILED, "message": "bash 缺失", "metric_status": "UNKNOWN"},
        )
        doc = n.normalize_host_result(hr, run_id=RUN_ID, collected_at=COLLECTED)
        assert doc["execution_status"] == "ERROR"
        assert doc["metrics"] == []

    def test_execution_business_separation(self):
        # 部分指标失败 → PARTIAL；失败指标 UNKNOWN；成功指标正常业务判定
        ok_metric = metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))
        stderr_file = FIXTURE_DIR / "node-b" / "local.cpu.utilization.stderr"
        bad_metric = metric_result(
            "local.cpu.utilization",
            raw("node-b", "local.cpu.utilization"),
            stderr=stderr_file.read_text(encoding="utf-8"),
            error={"code": n.ERROR_PERMISSION_DENIED, "message": "权限不足", "metric_status": "UNKNOWN"},
        )
        doc = n.normalize_host_result(
            host_result("node-b", [ok_metric, bad_metric]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert doc["execution_status"] == "PARTIAL"
        assert doc["execution_summary"]["executed"] == 1
        assert doc["execution_summary"]["failed"] == 1
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert by_id["local.cpu.utilization"]["status"] == "UNKNOWN"
        assert by_id["local.cpu.load_1m"]["status"] == "OK"


# --------------------------------------------------------------------------
# 7. 与 T-103 fixture 模式端到端管道（node-a/b/c/d/e）
# --------------------------------------------------------------------------


def pipeline(host: str, tmp_path: Path, hosts=None):
    """ansible_runner fixture 模式 run() → normalize_run_results 全链路。"""
    specs = ar.build_metric_command_specs(profile=PROFILE)
    selection = SimpleNamespace(
        inventory_file=str(tmp_path / "inv.ini"),
        hosts=hosts
        or [SimpleNamespace(name=host, ip="10.0.0.1")],
        limit=None,
    )
    run_result = ar.run(
        selection, specs, fixture_dir=FIXTURE_DIR, runtime_dir=tmp_path / "runtime"
    )
    return n.normalize_run_results(run_result, run_id=RUN_ID, collected_at=COLLECTED, profile=PROFILE)


class TestPipeline:
    def test_pipeline_node_a(self, tmp_path):
        out = pipeline("node-a", tmp_path)
        assert out["execution_status"] == "SUCCESS"
        (doc,) = out["documents"]
        assert doc["host"]["name"] == "node-a"
        assert doc["host"]["ip"] == "<IP>"
        assert doc["inspection_id"] == "insp-20260815103000-node-a"
        summary = doc["execution_summary"]
        assert summary == {
            "total_metrics": 10,
            "ok": 7,
            "warn": 1,
            "crit": 1,
            "unknown": 1,
            "executed": 10,
            "failed": 0,
        }
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert by_id["local.port.listening"]["status"] == "WARN"  # 5601 模式外 C7
        assert by_id["local.filesystem.used_percent"]["status"] == "CRIT"  # 91%
        assert by_id["local.logs.key_evidence"]["status"] == "UNKNOWN"  # 3 命中 C10
        assert by_id["local.process.present"]["status"] == "OK"
        n.validate_host_result(doc)

    def test_pipeline_node_b_partial(self, tmp_path):
        out = pipeline("node-b", tmp_path)
        assert out["execution_status"] == "PARTIAL"
        (doc,) = out["documents"]
        assert doc["execution_summary"]["ok"] == 6
        assert doc["execution_summary"]["unknown"] == 4
        assert doc["execution_summary"]["executed"] == 7
        assert doc["execution_summary"]["failed"] == 3
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert by_id["local.process.present"]["error"]["code"] == n.ERROR_COMMAND_NOT_FOUND
        assert by_id["local.port.listening"]["error"]["code"] == n.ERROR_TIMEOUT
        assert by_id["local.cpu.utilization"]["error"]["code"] == n.ERROR_PERMISSION_DENIED
        assert by_id["local.logs.key_evidence"]["status"] == "UNKNOWN"
        for mid in (
            "local.service.active",
            "local.cpu.load_1m",
            "local.memory.available_percent",
            "local.swap.used_percent",
            "local.filesystem.used_percent",
            "local.filesystem.inode_used_percent",
        ):
            assert by_id[mid]["status"] == "OK"

    def test_pipeline_node_c_connection_failed(self, tmp_path):
        out = pipeline("node-c", tmp_path)
        (doc,) = out["documents"]
        assert doc["execution_status"] == "ERROR"
        assert doc["metrics"] == []
        # 连接失败 → 无业务结论：无指标被采集（T-103 build_host_result
        # summary.total=0，normalize 忠实保留；计划数信息不在此文档内）
        assert doc["execution_summary"]["total_metrics"] == 0
        assert doc["execution_summary"]["failed"] == 0
        assert out["host_errors"]["node-c"]["code"] == n.ERROR_CONNECTION_FAILED

    def test_pipeline_node_d_probe_failed(self, tmp_path):
        out = pipeline("node-d", tmp_path)
        (doc,) = out["documents"]
        assert doc["execution_status"] == "ERROR"
        assert out["host_errors"]["node-d"]["code"] == n.ERROR_PROBE_FAILED

    def test_pipeline_node_e_data_missing(self, tmp_path):
        out = pipeline("node-e", tmp_path)
        assert out["execution_status"] == "PARTIAL"
        (doc,) = out["documents"]
        assert doc["execution_summary"]["ok"] == 1
        assert doc["execution_summary"]["unknown"] == 9
        assert doc["execution_summary"]["failed"] == 9
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert by_id["local.cpu.load_1m"]["status"] == "OK"
        assert by_id["local.service.active"]["error"]["code"] == n.ERROR_DATA_MISSING


# --------------------------------------------------------------------------
# 8. inspection_id / meta / 结构
# --------------------------------------------------------------------------


class TestStructure:
    def test_make_inspection_id_format(self):
        from datetime import datetime

        assert n.make_inspection_id("node-01", datetime(2026, 8, 14, 12, 0, 0)) == (
            "insp-20260814120000-node-01"
        )

    def test_make_inspection_id_sanitizes(self):
        from datetime import datetime

        assert n.make_inspection_id("node a/01", datetime(2026, 8, 14, 12, 0, 0)) == (
            "insp-20260814120000-node-a-01"
        )

    def test_meta_default(self):
        doc = n.normalize_host_result(
            host_result("node-test", [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert doc["meta"] == {
            "control_endpoint": "Linux/WSL Python3",
            "gather_facts": False,
            "serial": 1,
            "become_scope": "minimal",
            "generator": "inspect.sh",
            "generator_version": "0.1.0-draft",
        }

    def test_top_level_keys_exact(self):
        doc = n.normalize_host_result(
            host_result("node-test", [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert set(doc) == n.TOP_KEYS
        assert doc["schema"] == "host-result-v1"
        assert doc["schema_version"] == 1
        assert doc["run_id"] == RUN_ID

    def test_metric_required_fields_exact(self):
        doc = n.normalize_host_result(
            host_result("node-a", [metric_result(m, raw("node-a", m)) for m in metrics_mod.ALL_METRIC_IDS]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        for metric in doc["metrics"]:
            assert set(metric) == n.METRIC_KEYS
            assert set(metric["threshold"]) == n.THRESHOLD_KEYS
            assert n.EVIDENCE_KEYS.issubset(metric["evidence"])
            if metric["metric_id"] in {
                "local.filesystem.used_percent",
                "local.filesystem.inode_used_percent",
            }:
                assert len(metric["evidence"]["details"]) == 2
                assert all(
                    set(detail) == {"filesystem", "mount", "used_percent", "status"}
                    for detail in metric["evidence"]["details"]
                )
            elif metric["metric_id"] == "local.cpu.load_1m":
                assert [d["window"] for d in metric["evidence"]["details"]] == ["1 分钟", "5 分钟", "15 分钟"]
                assert all(
                    set(detail) == {"window", "load", "cpu_cores", "status", "judgement"}
                    for detail in metric["evidence"]["details"]
                )
            else:
                assert "details" not in metric["evidence"]
            assert set(metric["provenance"]) == n.PROVENANCE_KEYS

    def test_filesystem_evidence_details_and_max_value_are_compatible(self):
        results = [
            metric_result("local.filesystem.used_percent", raw("node-a", "local.filesystem.used_percent")),
            metric_result("local.filesystem.inode_used_percent", raw("node-a", "local.filesystem.inode_used_percent")),
        ]
        doc = n.normalize_host_result(
            host_result("node-a", results),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        by_id = {metric["metric_id"]: metric for metric in doc["metrics"]}
        disk = by_id["local.filesystem.used_percent"]
        inode = by_id["local.filesystem.inode_used_percent"]
        assert disk["normalized_value"] == 91.0
        assert disk["raw_value"] == "91"
        assert [d["mount"] for d in disk["evidence"]["details"]] == ["/", "/data"]
        assert [d["status"] for d in disk["evidence"]["details"]] == [n.STATUS_OK, n.STATUS_CRIT]
        assert inode["normalized_value"] == 1.0
        assert [d["mount"] for d in inode["evidence"]["details"]] == ["/", "/data"]
        assert [d["status"] for d in inode["evidence"]["details"]] == [n.STATUS_OK, n.STATUS_OK]
        n.validate_host_result(doc)


    def test_filesystem_detail_status_uses_each_mount_value(self):
        metric = normalize_one(
            "local.filesystem.used_percent",
            "Filesystem Type Size Used Avail Use% Mounted on\n"
            "/dev/root ext4 100G 61G 39G 61% /\n"
            "/dev/data ext4 100G 83G 17G 83% /data\n",
        )
        details = metric["evidence"]["details"]
        assert metric["status"] == n.STATUS_WARN
        assert [d["status"] for d in details] == [n.STATUS_OK, n.STATUS_WARN]

    def test_filesystem_detail_status_respects_external_rules(self):
        resolved = override_resolved(
            {
                "local.filesystem.used_percent": {
                    "rules": [
                        {"status": "CRIT", "op": ">=", "value": 80, "note": "critical threshold"},
                        {"status": "WARN", "op": ">=", "value": 50, "note": "warning threshold"},
                    ]
                }
            }
        )
        metric = normalize_one(
            "local.filesystem.used_percent",
            "Filesystem Type Size Used Avail Use% Mounted on\n"
            "/dev/root ext4 100G 10G 90G 10% /\n"
            "/dev/data ext4 100G 85G 15G 85% /data\n",
            resolved=resolved,
        )
        assert metric["status"] == n.STATUS_CRIT
        assert [d["status"] for d in metric["evidence"]["details"]] == [n.STATUS_OK, n.STATUS_CRIT]

    def test_registry_alignment_with_metrics_py(self):
        assert set(n.PARSERS) == set(metrics_mod.ALL_METRIC_IDS)
        assert set(n.JUDGERS) == set(metrics_mod.ALL_METRIC_IDS)
        for metric_id, parser_name in n.PARSER_NAMES.items():
            assert n.PARSERS[metric_id].__name__ == parser_name


# --------------------------------------------------------------------------
# 9. validate_host_result（内嵌 schema 语义子集）
# --------------------------------------------------------------------------


def _valid_doc() -> dict:
    doc = n.normalize_host_result(
        host_result("node-test", [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))]),
        run_id=RUN_ID,
        collected_at=COLLECTED,
    )
    return doc


class TestValidation:
    def test_validate_accepts_normalized_doc(self):
        n.validate_host_result(_valid_doc())

    def test_validate_rejects_missing_top_key(self):
        doc = _valid_doc()
        del doc["execution_summary"]
        with pytest.raises(ValueError, match="execution_summary"):
            n.validate_host_result(doc)

    def test_validate_rejects_extra_key(self):
        doc = _valid_doc()
        doc["extra"] = 1
        with pytest.raises(ValueError, match="extra"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_execution_status(self):
        doc = _valid_doc()
        doc["execution_status"] = "FAILED"
        with pytest.raises(ValueError, match="execution_status"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_inspection_id(self):
        doc = _valid_doc()
        doc["inspection_id"] = "insp-123-node"
        with pytest.raises(ValueError, match="inspection_id"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_meta(self):
        doc = _valid_doc()
        doc["meta"]["serial"] = 2
        with pytest.raises(ValueError, match="meta.serial"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_metric_status(self):
        doc = _valid_doc()
        doc["metrics"][0]["status"] = "FATAL"
        with pytest.raises(ValueError, match="status"):
            n.validate_host_result(doc)

    def test_validate_rejects_error_with_business_status(self):
        doc = _valid_doc()
        metric = doc["metrics"][0]
        metric["error"] = {
            "code": n.ERROR_TIMEOUT,
            "message": "超时",
            "metric_status": "UNKNOWN",
        }
        metric["status"] = "OK"
        with pytest.raises(ValueError, match="error 存在时 status"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_error_code(self):
        doc = _valid_doc()
        metric = doc["metrics"][0]
        metric["error"] = {"code": "BOGUS", "message": "x", "metric_status": "UNKNOWN"}
        metric["status"] = "UNKNOWN"
        with pytest.raises(ValueError, match="error.code"):
            n.validate_host_result(doc)

    def test_validate_rejects_bad_threshold_layer(self):
        doc = _valid_doc()
        doc["metrics"][0]["threshold"]["layer"] = "invented-layer"
        with pytest.raises(ValueError, match="threshold.layer"):
            n.validate_host_result(doc)


# --------------------------------------------------------------------------
# 10. T-104F：派生标识符安全映射（IP/含凭据关键字 host 键 → inspection_id
#     合法且可落盘；业务字段脱敏不受影响）
# --------------------------------------------------------------------------

_INSPECTION_ID_PATTERN = re.compile(r"^insp-[0-9]{14}-[A-Za-z0-9_.-]+$")


def _persist_or_skip(tmp_path: Path, doc: dict):
    """T-104F 落盘证据：真实写入 fact_source 并回读。

    host 名按脱敏规则输出为 `<IP>`/`node-<REDACTED>-01`，其中 `<`/`>`
    在 Windows 是非法的文件名字符（fact_source 文件名边界，非本任务
    owned_paths）；Linux/WSL 目标环境可正常写入。Windows 上该平台约束
    命中时 skip 并注明——落盘闸门（validate_host_result，缺陷 exit 10
    发生点）的断言在 skip 之前已执行。
    """
    import sys

    try:
        return fs.write_host_result(tmp_path, doc)
    except fs.FactSourceError as exc:
        if sys.platform == "win32" and "[Errno 22]" in str(exc):
            pytest.skip(f"Windows 文件名禁止 <>（fact_source 命名边界）: {exc}")
        raise


class TestInspectionIdSafeMapping:
    """T-104F 回归：host 键为 IP/含凭据关键字时，inspection_id 不得被
    文档级强制脱敏扫描改写为 `insp-<ts>-<IP>`/`insp-<ts>-node-<REDACTED>-01`
    （`<`/`>` 不在 schema pattern 字符集内 → validate_host_result 拒绝 →
    事实源落盘 exit 10）。修复后派生 ID 先做安全字符集映射
    （IP→ip、凭据特征→redacted）再对业务字段脱敏，输出必过自身 schema
    校验且可落盘。"""

    def test_make_inspection_id_safe_mapping(self):
        from datetime import datetime

        when = datetime(2026, 8, 14, 12, 0, 0)
        assert n.make_inspection_id("192.168.1.1", when) == (
            "insp-20260814120000-ip"
        )
        assert n.make_inspection_id("node-secret-01", when) == (
            "insp-20260814120000-node-redacted-01"
        )
        assert n.make_inspection_id("fe80::1", when) == "insp-20260814120000-ip"
        # 无 IP/凭据的普通 host 键行为不变
        assert n.make_inspection_id("node-01", when) == "insp-20260814120000-node-01"

    def test_ip_host_key_inspection_id_valid_and_persists(self, tmp_path):
        doc = n.normalize_host_result(
            host_result(
                "192.168.1.1",
                [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))],
            ),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert _INSPECTION_ID_PATTERN.fullmatch(doc["inspection_id"])
        assert doc["inspection_id"].endswith("-ip")  # IP → ip 占位，非 <IP>
        assert "<IP>" not in doc["inspection_id"]
        assert doc["host"]["name"] == "<IP>"  # host 名按脱敏规则处理
        assert not n.contains_plain_ip(doc_json_text(doc))
        n.validate_host_result(doc)  # 落盘闸门（缺陷 exit 10 发生点）
        info = _persist_or_skip(tmp_path, doc)  # 真实落盘 + 回读
        if info is not None:
            on_disk = fs.read_host_result(info["file"])
            assert on_disk["inspection_id"] == doc["inspection_id"]

    def test_secret_host_key_inspection_id_valid_and_persists(self, tmp_path):
        doc = n.normalize_host_result(
            host_result(
                "node-secret-01",
                [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))],
            ),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert _INSPECTION_ID_PATTERN.fullmatch(doc["inspection_id"])
        assert "secret" not in doc["inspection_id"]  # 凭据关键字 → redacted
        assert "redacted" in doc["inspection_id"]
        assert "<REDACTED>" not in doc["inspection_id"]
        assert doc["host"]["name"] == "node-<REDACTED>-01"  # host 名按脱敏规则处理
        assert not n.contains_credential(doc_json_text(doc))
        n.validate_host_result(doc)  # 落盘闸门（缺陷 exit 10 发生点）
        info = _persist_or_skip(tmp_path, doc)  # 真实落盘 + 回读
        if info is not None:
            on_disk = fs.read_host_result(info["file"])
            assert on_disk["inspection_id"] == doc["inspection_id"]

    def test_derived_id_sweep_is_noop(self):
        # 派生 ID 已安全映射 → 文档级强制脱敏扫描不改写 ID（幂等）
        doc = n.normalize_host_result(
            host_result(
                "192.168.1.1",
                [metric_result("local.cpu.load_1m", raw("node-a", "local.cpu.load_1m"))],
            ),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        from datetime import datetime

        when = datetime.fromisoformat(COLLECTED)
        assert doc["inspection_id"] == n.make_inspection_id("192.168.1.1", when)

    def test_business_masking_unaffected_with_ip_host_key(self):
        # 业务字段脱敏不受影响：IP host 键 + 解析器漏脱敏的对抗输出
        evil = "4321 java 192.168.5.10:3306 -Dpassword=Admin@123 https://u:p@h/secret"
        doc = n.normalize_host_result(
            host_result("192.168.1.1", [metric_result("local.process.present", evil)]),
            run_id=RUN_ID,
            collected_at=COLLECTED,
        )
        assert _INSPECTION_ID_PATTERN.fullmatch(doc["inspection_id"])
        text = doc_json_text(doc)
        assert "<REDACTED>" in text  # 对抗输入仍被强制扫描
        assert not n.contains_plain_ip(text)
        assert not n.contains_credential(text)
        n.validate_host_result(doc)
