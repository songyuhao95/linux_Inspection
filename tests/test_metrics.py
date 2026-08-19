"""T-101 指标注册表测试：10 个 P0 指标、必填字段、来源锚点、超时约定。

契约：docs/specs/local-metrics-requirements.md §5（字段/锚点/超时）与
§2（字段缺失即定义不完整）；本测试机械校验注册表完整性。
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inspect import metrics as reg  # noqa: E402

EXPECTED_IDS = [
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
    "local.nginx.process.present",
    "local.nginx.config.valid",
    "local.nginx.port.listening",
    "local.nginx.error_log.key_evidence",
    "local.nginx.connections.status",
    "local.nginx.access_log.status_codes",
    "local.nginx.config.baseline",
    "local.nginx.security.baseline",
]

# MR §5 超时列：指标命令 10s、日志类 15s（TD §5.2）
LOG_IDS = {
    "local.logs.key_evidence",
    "local.nginx.error_log.key_evidence",
    "local.nginx.access_log.status_codes",
}
TIMEOUT_10S = set(EXPECTED_IDS) - LOG_IDS


def test_registry_has_exactly_18_metrics():
    """注册表共 18 条（10 个共同 P0 + 8 个 Nginx 中间件）。"""
    assert reg.count_metrics() == 18
    assert len(reg.METRICS) == 18


def test_metric_ids_are_exact_expected_set():
    """metric_id 集合与 EXPECTED_IDS 完全一致（顺序即注册顺序）。"""
    assert reg.ALL_METRIC_IDS == tuple(EXPECTED_IDS)


def test_metric_ids_unique():
    ids = [m["metric_id"] for m in reg.METRICS]
    assert len(ids) == len(set(ids))


def test_required_fields_present_and_nonempty():
    """MR §2 必填字段：缺失即指标定义不完整 → 测试失败。"""
    for m in reg.METRICS:
        for field in reg.REQUIRED_FIELDS:
            assert field in m, f"{m.get('metric_id')} 缺字段 {field}"
        assert str(m["metric_id"]).startswith("local.")
        for text_field in (
            "name", "command", "parser", "unit",
            "source_anchor", "threshold_layer", "doc_baseline", "unknown_conditions",
        ):
            assert str(m[text_field]).strip(), f"{m['metric_id']} 的 {text_field} 为空"
        assert m["timeout_sec"] in (10, 15), f"{m['metric_id']} 超时须为 10s 或 15s"
        assert isinstance(m["threshold_rule_ids"], list) and m["threshold_rule_ids"]


def test_registry_field_contract_exact_keys():
    """字段契约：每个条目键集必须与 REQUIRED_FIELDS 完全一致（防增删漂移）。"""
    for m in reg.METRICS:
        assert set(m.keys()) == set(reg.REQUIRED_FIELDS), m["metric_id"]


def test_timeout_convention():
    """超时约定：日志类 15s，其余 10s（MR §5 超时列）。"""
    for m in reg.METRICS:
        if m["metric_id"] in TIMEOUT_10S:
            assert m["timeout_sec"] == 10
        else:
            assert m["timeout_sec"] == 15


def test_source_anchors_reference_manuals_and_sha256():
    """来源锚点：含手册/章节/表位置与文件 sha256[:8]（MR §2 格式）。"""
    for m in reg.METRICS:
        a = m["source_anchor"]
        assert "巡检手册" in a, f"{m['metric_id']} 锚点缺手册引用"
        assert re.search(r"[0-9a-f]{8}", a), f"{m['metric_id']} 锚点缺 sha256 指纹"


def test_anchor_table_positions():
    """锚点含表位置 T#R#（MR §5 来源锚点列）。

    Nginx 手册指标表没有 T#R# 编号，改用「P0/P1 指标表」段落定位；
    共同 P0 指标仍要求 T#R#。
    """
    for m in reg.METRICS:
        if m["metric_id"].startswith("local.nginx."):
            assert "指标表" in m["source_anchor"], m["metric_id"]
        else:
            assert re.search(r"T\d+R\d+", m["source_anchor"]), m["metric_id"]


def test_parser_names_unique():
    """解析器名唯一（T-104 normalize 按名注册）。

    两个通用解析器（parse_process_present / parse_logs_key_evidence）被
    Nginx 指标复用是有意的：进程存在性与日志命中判定与共同 P0 语义一致。
    """
    parsers = [m["parser"] for m in reg.METRICS]
    shared = {
        "parse_process_present",
        "parse_logs_key_evidence",
    }
    unique = [p for p in parsers if p not in shared]
    assert len(unique) == len(set(unique))
    # 共享解析器的复用次数是有界且固定的：parse_process_present 被
    # local.process.present 与 local.nginx.process.present 复用；
    # parse_logs_key_evidence 只被 local.logs.key_evidence 使用
    # （nginx 关键日志用带 ls 标记剥离的 parse_nginx_error_log）。
    assert parsers.count("parse_process_present") == 2
    assert parsers.count("parse_logs_key_evidence") == 1


def test_threshold_rule_ids_reference_version():
    """阈值规则 ID 引用文档基线版本标识（linux-common-p0-v1 / nginx-p0-v1）。"""
    for m in reg.METRICS:
        prefix = reg.NGINX_RULE_PREFIX if m["metric_id"].startswith("local.nginx.") else reg.VERSION
        for rid in m["threshold_rule_ids"]:
            assert rid.startswith(prefix + ":"), f"{m['metric_id']} 规则 ID 前缀错误"


def test_get_metric_lookup():
    """get_metric 按 ID 命中，未知 ID 返回 None。"""
    assert reg.get_metric("local.cpu.utilization")["name"] == "CPU 使用率"
    assert reg.get_metric("local.no.such") is None


def test_status_mapping_invariant():
    """状态映射不变量（MR §3/§4/§6）。

    - 每个指标必定义 OK 判据与 UNKNOWN 路径（权限/能力失败、缺失边界一律
      UNKNOWN，MR §2）；WARN/CRIT 因缺失边界（C1/C3/C4/C5 等）按文档
      允许缺失——禁止发明阈值，故不要求每个指标四状态齐备；
    - 注册表整体覆盖 OK/WARN/CRIT/UNKNOWN 四状态（MR §4 映射被表达）。
    """
    covered = set()
    for m in reg.METRICS:
        text = m["doc_baseline"] + " " + m["unknown_conditions"]
        assert "OK" in text, f"{m['metric_id']} 缺 OK 判据"
        assert "UNKNOWN" in text, f"{m['metric_id']} 缺 UNKNOWN 路径"
        for token in ("OK", "WARN", "CRIT", "UNKNOWN"):
            if token in text:
                covered.add(token)
    assert covered == {"OK", "WARN", "CRIT", "UNKNOWN"}
