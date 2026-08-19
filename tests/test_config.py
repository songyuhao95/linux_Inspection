"""T-102 配置层与阈值 override 测试（contract-T-102-v1 的 AC-3 执行面）。

覆盖：
  - 文档基线加载：恰好 10 指标、MR §6 阈值汇总表逐项转写值（禁止发明/调整阈值，
    差异即停止条件）、source_anchor、rule_id 版本前缀、UNKNOWN reason/note 语义
    （C1/C2 none、C3/C8 conflict、C4/C5 missing）；
  - 阈值分层合并（外部配置 > 文档基线 > UNKNOWN）：无 override → document-baseline；
    override → external-config + provenance（config_sources/doc_sources/notes）；
    仅 override 出现的指标收录；无任何定义边界的指标 → unresolved-document-conflict；
  - override 校验（TD §6.2/§7.2）：合法文档接受并规范化；未知 status/op、缺 note、
    双重判定、未知字段、range/value 类型错误、空 rules、非 local.* 指标键、
    schema/version 不匹配一律 ConfigError 拒绝；
  - JSON Schema 文件结构与 mini draft-07 子集校验器（机器可执行性证明，
    jsonschema 库为 dev 依赖且本机未安装，故以最小语义实现验证）；
  - inspect.yml 加载与默认值（TD §6.3）；
  - 严格 YAML 子集解析器边界（引号/注释/flow/类型/重复键/制表符等）。
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 模块加载：集成环境（inspect/__init__.py 存在）用真实包；worktree 无
# __init__.py 时从文件加载（包名与 stdlib inspect 同名问题见 T-101 report §5
# 风险 2；本文件不触碰 sys.modules['inspect']，避免影响 pytest 对 stdlib 的使用）
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]
_CONFIG_PY = _REPO / "inspect" / "config.py"
_BASELINE_YAML = _REPO / "inspect" / "data" / "thresholds" / "linux-common-p0-v1.yaml"
_SCHEMA_JSON = _REPO / "inspect" / "schema" / "threshold-override-v1.schema.json"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "config"


def _load_config_module():
    try:
        import inspect.config  # noqa: F401
    except ImportError:
        pass
    else:
        top = sys.modules.get("inspect")
        pkg_file = getattr(top, "__file__", None)
        if pkg_file:
            resolved = Path(pkg_file).resolve()
            if resolved.parent == (_REPO / "inspect").resolve() or str(resolved).startswith(
                str((_REPO / "inspect").resolve())
            ):
                return sys.modules["inspect.config"]
    spec = importlib.util.spec_from_file_location("t102_inspect_config", _CONFIG_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cfg = _load_config_module()

# ---------------------------------------------------------------------------
# MR §6 阈值汇总表（local-metrics-requirements.md §6，2026-08-15 核对）——
# 唯一权威阈值来源；与基线文件必须逐字一致，任何差异即停止条件。
# 注意：process.present WARN 单元格为 "反复重启"（§5.1 文档基线行为
# "服务反复重启"，汇总表简写；以 §6 汇总表为转写基准）。
# ---------------------------------------------------------------------------

EXPECTED_METRIC_IDS = [
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

# MR §6 表格"已定义"单元格（未列出的层 = "（文档未定义）" → rule: null）
MR_SECTION6_RULES = {
    "local.process.present": {
        "OK": "进程存在", "WARN": "反复重启", "CRIT": "进程缺失（故障）",
    },
    "local.service.active": {
        "OK": "active", "WARN": "反复重启", "CRIT": "非 active（故障）",
    },
    "local.port.listening": {
        "OK": "监听且进程匹配", "WARN": "模式外端口开放", "CRIT": "不监听（故障）",
    },
    "local.cpu.utilization": {
        "OK": "长期<70% 且波动<80%", "WARN": "持续>80%", "CRIT": ">90% 且伴随业务证据",
    },
    "local.cpu.load_1m": {"OK": "≤核数"},
    "local.memory.available_percent": {"OK": "≥20%", "CRIT": "<10%"},
    "local.swap.used_percent": {"OK": "=0 或未配置"},
    "local.filesystem.used_percent": {
        "OK": "<75%（Nginx/Tomcat <80%）", "WARN": "75–85%", "CRIT": ">85%（>95% 故障风险）",
    },
    "local.filesystem.inode_used_percent": {"OK": "<80%"},
    "local.logs.key_evidence": {
        "OK": "无可解释错误", "WARN": "隐患级关键词（按产品）", "CRIT": "故障级关键词（按产品）",
    },
}

# MR §6 表格"无规则/冲突 → UNKNOWN 边界"列 + 冲突裁决（docs/reviews/docx-source-conflicts.md）：
# C1/C2 resolved → reason=none；C3/C8 unresolved → reason=conflict；C4（缺失边界）、C5 → missing
MR_SECTION6_UNKNOWN = {
    "local.process.present": ("missing", "无 profile 配置"),
    "local.service.active": ("conflict", "unit 名无配置/冲突 C8"),
    "local.port.listening": ("missing", "端口/模式无配置"),
    "local.cpu.utilization": ("none", "Nginx/Tomcat 差异 C2"),
    "local.cpu.load_1m": ("missing", "持续>核数 → 缺失 → UNKNOWN"),
    "local.memory.available_percent": ("missing", "10–20% 区间 C4"),
    "local.swap.used_percent": ("conflict", ">0 → 冲突 C3 → UNKNOWN"),
    "local.filesystem.used_percent": ("none", "建议线冲突 C1（外部配置覆盖）"),
    "local.filesystem.inode_used_percent": ("missing", "≥80% → 缺失 C5 → UNKNOWN"),
    "local.logs.key_evidence": ("missing", "日志不可读/关键词集无配置"),
}

INVALID_OVERRIDE_CASES = [
    ("override_bad_status.yml", "status"),
    ("override_bad_op.yml", "op"),
    ("override_missing_note.yml", "note"),
    ("override_double_rule.yml", "双重判定"),
    ("override_extra_key.yml", "未知字段"),
    ("override_bad_range.yml", "range"),
    ("override_bad_value_type.yml", "value 必须为数值"),
    ("override_empty_rules.yml", "rules 必须为非空"),
    ("override_nonlocal_metric.yml", "必须匹配 ^local\\."),
    ("override_missing_rules.yml", "缺少 rules"),
    ("override_bad_version.yml", "version 不匹配"),
]


# ---------------------------------------------------------------------------
# 文档基线
# ---------------------------------------------------------------------------


def test_baseline_exactly_10_metrics_in_mr_order():
    baseline = cfg.load_document_baseline()
    assert list(baseline) == EXPECTED_METRIC_IDS[:10]
    nginx = cfg.load_nginx_baseline()
    assert list(nginx) == EXPECTED_METRIC_IDS[10:]


def test_baseline_rules_match_mr_section6_verbatim():
    baseline = cfg.load_document_baseline()
    for metric_id, spec in baseline.items():
        boundaries = spec["boundaries"]
        for status in ("OK", "WARN", "CRIT"):
            defined = status in MR_SECTION6_RULES[metric_id]
            entry = boundaries[status]
            if defined:
                assert entry["rule"] == MR_SECTION6_RULES[metric_id][status], (
                    f"{metric_id}.{status} 与 MR §6 不一致"
                )
            else:
                assert entry["rule"] is None, (
                    f"{metric_id}.{status} MR §6 未定义，rule 必须为 null"
                )


def test_baseline_unknown_reason_and_note_per_conflicts():
    baseline = cfg.load_document_baseline()
    for metric_id, (reason, note) in MR_SECTION6_UNKNOWN.items():
        entry = baseline[metric_id]["boundaries"]["UNKNOWN"]
        assert entry["rule"] is None
        assert entry["reason"] == reason, metric_id
        assert entry["note"] == note, metric_id


def test_baseline_anchors_and_rule_ids():
    baseline = cfg.load_document_baseline()
    for metric_id, spec in baseline.items():
        assert spec["version"] == cfg.DOC_BASELINE_VERSION
        anchor = spec["source_anchor"]
        assert anchor.startswith("巡检手册") or "巡检手册" in anchor, metric_id
        slug = metric_id.split(".", 1)[1]
        for status in ("OK", "WARN", "CRIT"):
            entry = spec["boundaries"][status]
            if entry["rule"] is not None:
                assert entry["rule_id"] == (
                    f"{cfg.DOC_BASELINE_VERSION}.{slug}.{status.lower()}"
                ), metric_id
            else:
                assert entry["rule_id"] is None


def test_baseline_file_contains_ac1_markers():
    text = _BASELINE_YAML.read_text(encoding="utf-8")
    for marker in ("local.process.present", "local.cpu.utilization",
                   "source_anchor", "linux-common-p0-v1"):
        assert marker in text


# ---------------------------------------------------------------------------
# 阈值分层合并与 provenance（HR §4 / MR §3 固定顺序）
# ---------------------------------------------------------------------------


def test_no_override_all_document_baseline():
    resolved = cfg.build_resolved_thresholds()
    assert set(resolved) == set(EXPECTED_METRIC_IDS)
    for metric_id, entry in resolved.items():
        expected_version = (
            cfg.NGINX_BASELINE_VERSION
            if metric_id.startswith("local.nginx.")
            else cfg.DOC_BASELINE_VERSION
        )
        assert entry["layer"] == cfg.LAYER_DOCUMENT_BASELINE, metric_id
        assert entry["version"] == expected_version, metric_id
        assert entry["provenance"]["config_sources"] == []
        assert len(entry["provenance"]["doc_sources"]) == 1
        assert entry["provenance"]["notes"] is None
        assert entry["rules"], f"{metric_id} 至少应有 OK 边界"
        assert entry["unknown"]["reason"] in ("missing", "conflict", "none")


def test_resolved_rules_shape():
    resolved = cfg.build_resolved_thresholds()
    ok_rule = resolved["local.cpu.utilization"]["rules"][0]
    assert ok_rule == {
        "status": "OK",
        "rule": "长期<70% 且波动<80%",
        "rule_id": "linux-common-p0-v1.cpu.utilization.ok",
    }


def test_override_covers_and_provenance_records():
    override_path = _FIXTURES / "override_valid.yml"
    baseline = cfg.load_document_baseline()
    resolved = cfg.build_resolved_thresholds(override=override_path)

    covered = {"local.swap.used_percent", "local.filesystem.inode_used_percent",
               "local.cpu.load_1m"}
    for metric_id in covered:
        entry = resolved[metric_id]
        assert entry["layer"] == cfg.LAYER_EXTERNAL_CONFIG, metric_id
        assert entry["provenance"]["config_sources"] == [str(override_path)]
        # 覆盖后仍保留文档基线来源锚点
        assert entry["provenance"]["doc_sources"] == [
            baseline[metric_id]["source_anchor"]
        ]
        assert entry["provenance"]["notes"], metric_id

    swap = resolved["local.swap.used_percent"]
    assert swap["rules"] == [{
        "status": "WARN", "op": ">", "value": 0.0, "range": None,
        "note": "现场基线：启用 swap 监控（覆盖 C3）",
    }]
    assert "覆盖 C3" in swap["provenance"]["notes"]

    for metric_id in set(EXPECTED_METRIC_IDS) - covered:
        assert resolved[metric_id]["layer"] == cfg.LAYER_DOCUMENT_BASELINE, metric_id


def test_override_range_normalized():
    override_path = _FIXTURES / "override_range.yml"
    resolved = cfg.build_resolved_thresholds(override=override_path)
    rule = resolved["local.memory.available_percent"]["rules"][0]
    assert rule == {
        "status": "WARN", "op": None, "value": None, "range": [10.0, 20.0],
        "note": "现场基线：10–20% 区间告警（覆盖 C4 缺失边界）",
    }


def test_override_rule_order_preserved_first_match_wins():
    resolved = cfg.build_resolved_thresholds(override=_FIXTURES / "override_multi_rule.yml")
    rules = resolved["local.swap.used_percent"]["rules"]
    assert [r["status"] for r in rules] == ["OK", "WARN", "CRIT"]
    assert [r["op"] for r in rules] == ["==", ">", ">"]
    assert [r["value"] for r in rules] == [0.0, 0.0, 50.0]


def test_override_path_and_dict_arguments_equivalent():
    path = _FIXTURES / "override_valid.yml"
    from_path = cfg.build_resolved_thresholds(override=path)
    from_dict = cfg.build_resolved_thresholds(
        override=cfg.load_override(path), override_source=str(path)
    )
    assert from_path == from_dict


def test_override_only_metric_included():
    ov = {
        "schema": "threshold-override-v1",
        "version": 1,
        "metrics": {
            "local.custom.metric": {
                "rules": [{"status": "WARN", "op": ">", "value": 0, "note": "自定义"}]
            }
        },
    }
    resolved = cfg.build_resolved_thresholds(override=ov, override_source="<test>")
    assert resolved["local.custom.metric"]["layer"] == cfg.LAYER_EXTERNAL_CONFIG
    assert resolved["local.custom.metric"]["provenance"]["config_sources"] == ["<test>"]
    assert "local.custom.metric" in resolved


def test_undefined_boundaries_layer_unresolved():
    mini = cfg.load_document_baseline(_FIXTURES / "baseline_mini.yml")
    resolved = cfg.build_resolved_thresholds(baseline=mini)
    assert resolved["local.test.defined"]["layer"] == cfg.LAYER_DOCUMENT_BASELINE
    assert resolved["local.test.undefined"]["layer"] == cfg.LAYER_UNRESOLVED
    assert resolved["local.test.undefined"]["rules"] == []
    assert resolved["local.test.undefined"]["unknown"]["reason"] == "missing"


# ---------------------------------------------------------------------------
# override 校验（TD §6.2 / §7.2 schema 语义镜像）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture,keyword", INVALID_OVERRIDE_CASES)
def test_invalid_overrides_rejected(fixture, keyword):
    with pytest.raises(cfg.ConfigError) as excinfo:
        cfg.load_override(_FIXTURES / fixture)
    assert keyword in str(excinfo.value)


def test_valid_override_accepted_and_normalized():
    doc = cfg.load_override(_FIXTURES / "override_valid.yml")
    assert doc["schema"] == "threshold-override-v1"
    assert doc["version"] == 1
    assert doc["scope"] is None
    assert doc["hosts"] is None
    assert set(doc["metrics"]) == {
        "local.swap.used_percent",
        "local.filesystem.inode_used_percent",
        "local.cpu.load_1m",
    }


def test_config_error_exit_code_is_exec_failure():
    err = cfg.ConfigError("测试")
    assert err.exit_code == 10


# ---------------------------------------------------------------------------
# JSON Schema 文件：结构（合同修订点：note 必填）与机器可执行性（mini draft-07）
# ---------------------------------------------------------------------------


def _load_schema():
    return json.loads(_SCHEMA_JSON.read_text(encoding="utf-8"))


def test_schema_file_is_valid_json_and_structure():
    schema = _load_schema()  # json.load 抛错即 AC-2 失败
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["title"] == "threshold-override-v1"
    assert schema["required"] == ["schema", "version", "metrics"]
    assert schema["properties"]["schema"]["const"] == "threshold-override-v1"
    assert schema["properties"]["version"]["const"] == 1
    assert schema["properties"]["metrics"]["propertyNames"]["pattern"] == "^local\\."

    rule = schema["definitions"]["metric_override"]["properties"]["rules"]["items"]
    assert rule["required"] == ["status", "note"]  # 合同：缺 note 必须被拒绝
    assert rule["properties"]["status"]["enum"] == ["OK", "WARN", "CRIT"]
    assert rule["properties"]["op"]["enum"] == [">", ">=", "<", "<=", "==", "!="]
    assert rule["properties"]["note"]["type"] == "string"
    assert rule["additionalProperties"] is False
    branches = [b["required"] for b in rule["oneOf"]]
    assert branches == [["op", "value"], ["range"]]  # 双重判定被 oneOf 拒绝


def _schema_type_matches(instance, type_name):
    if type_name == "object":
        return isinstance(instance, dict)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "null":
        return instance is None
    if type_name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    return True


def _schema_validate(instance, node, root):
    """draft-07 子集校验器：仅覆盖 threshold-override-v1.schema.json 用到的关键字。"""
    if "$ref" in node:
        target = root
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return _schema_validate(instance, target, root)
    if "type" in node:
        wanted = node["type"]
        wanted = [wanted] if isinstance(wanted, str) else wanted
        if not any(_schema_type_matches(instance, t) for t in wanted):
            return False
    if "const" in node and instance != node["const"]:
        return False
    if "enum" in node and instance not in node["enum"]:
        return False
    if "required" in node:
        if not isinstance(instance, dict):
            return False
        if any(k not in instance for k in node["required"]):
            return False
    if "properties" in node and isinstance(instance, dict):
        for key, sub in node["properties"].items():
            if key in instance and not _schema_validate(instance[key], sub, root):
                return False
    if "additionalProperties" in node and isinstance(instance, dict):
        if node["additionalProperties"] is False:
            if any(k not in node.get("properties", {}) for k in instance):
                return False
        else:
            for key, value in instance.items():
                if key not in node.get("properties", {}) and not _schema_validate(
                    value, node["additionalProperties"], root
                ):
                    return False
    if "propertyNames" in node and isinstance(instance, dict):
        pattern = re.compile(node["propertyNames"]["pattern"])
        if any(not pattern.match(key) for key in instance):
            return False
    if "items" in node and isinstance(instance, list):
        for item in instance:
            if not _schema_validate(item, node["items"], root):
                return False
    if "minItems" in node and isinstance(instance, list) and len(instance) < node["minItems"]:
        return False
    if "maxItems" in node and isinstance(instance, list) and len(instance) > node["maxItems"]:
        return False
    if "minLength" in node and isinstance(instance, str) and len(instance) < node["minLength"]:
        return False
    if "oneOf" in node:
        hits = sum(1 for sub in node["oneOf"] if _schema_validate(instance, sub, root))
        if hits != 1:
            return False
    return True


def _raw_doc(name):
    text = (_FIXTURES / name).read_text(encoding="utf-8")
    return cfg._parse_yaml_text(text, source=name)


def test_schema_accepts_valid_docs():
    schema = _load_schema()
    for name in ("override_valid.yml", "override_range.yml", "override_multi_rule.yml"):
        assert _schema_validate(_raw_doc(name), schema, schema) is True, name


def test_schema_rejects_invalid_docs():
    schema = _load_schema()
    for name, _keyword in INVALID_OVERRIDE_CASES:
        assert _schema_validate(_raw_doc(name), schema, schema) is False, name


# ---------------------------------------------------------------------------
# inspect.yml（TD §6.3）
# ---------------------------------------------------------------------------


def test_load_inspect_config_defaults_when_missing():
    # 仓库根无 inspect.yml（可选配置，缺省 out_dir=out）
    assert not (_REPO / "inspect.yml").is_file()
    conf = cfg.load_inspect_config()
    assert conf["schema"] == "inspect-config-v1"
    assert conf["version"] == 1
    assert conf["out_dir"] == "out"
    assert conf["inventory"] is None
    assert conf["profiles"] == {}


def test_load_inspect_config_fixture():
    conf = cfg.load_inspect_config(_FIXTURES / "inspect_config.yml")
    assert conf["out_dir"] == "out"
    assert conf["inventory"] is None
    es = conf["profiles"]["elasticsearch"]
    assert es["process_pattern"] == "org.elasticsearch.bootstrap.Elasticsearch"
    assert es["unit"] == "elasticsearch"
    assert es["ports"] == [9200, 9300]
    assert es["fs_paths"] == ["/opt/elasticsearch/data", "/opt/elasticsearch/logs"]
    assert es["log_paths"] == ["/opt/elasticsearch/logs/*.log"]
    assert es["log_keywords"] == [
        "ERROR", "master not discovered", "flood stage", "OutOfMemory"
    ]


def test_inspect_config_unknown_field_rejected():
    with pytest.raises(cfg.ConfigError) as excinfo:
        cfg.load_inspect_config(_FIXTURES / "inspect_config_bad_field.yml")
    assert "未知字段" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 严格 YAML 子集解析器
# ---------------------------------------------------------------------------


def test_yaml_parser_edge_cases():
    data = cfg._parse_yaml_text(
        (_FIXTURES / "yaml_parser_edge.yml").read_text(encoding="utf-8"),
        source="yaml_parser_edge.yml",
    )
    inner = data["nested"]["level_a"]["level_b"]
    assert inner["key"] == "value"
    assert inner["number"] == 42
    assert inner["float_value"] == 3.14
    assert inner["yes"] is True
    assert inner["no"] is False
    assert inner["nothing"] is None
    assert inner["tilde"] is None
    assert data["seq"] == [
        "item one",
        "item two",
        {"status": "OK", "op": ">", "value": 0},
        [1, 2, 3],
    ]
    assert data["flow_map"] == {"a": 1, "b": "two", "c": ["x", "y"]}
    assert data["quoted"] == "含空格与 # 井号的字符串"
    assert data["single"] == "单引号 '转义' 与 # 注释"
    assert data["escaped"] == "制表符\t换行\n反斜杠\\"


def test_yaml_parser_rejects_invalid(tmp_path):
    cases = {
        "tab_indent": "a:\n\tb: 1\n",
        "duplicate_key": "a: 1\na: 2\n",
        "unclosed_quote": 'a: "未闭合\n',
        "plain_colon_space": "a: b: c\n",
        "flow_tail_comma": "a: {x: 1,}\n",
        "flow_trailing_junk": "a: {x: 1} junk\n",
        "mixed_block": "a:\n  - x\n  y: 1\n",
    }
    for name, text in cases.items():
        f = tmp_path / f"{name}.yml"
        f.write_text(text, encoding="utf-8")
        with pytest.raises(cfg.ConfigError):
            cfg.load_override(f)


# ---------------------------------------------------------------------------
# AC 文本标记镜像（合同 AC-1/AC-4 的 UTF-8 断言，随 pytest 一并执行）
# ---------------------------------------------------------------------------


def test_config_py_contains_ac4_markers():
    text = _CONFIG_PY.read_text(encoding="utf-8")
    for marker in ("provenance", "document-baseline", "external-config"):
        assert marker in text
