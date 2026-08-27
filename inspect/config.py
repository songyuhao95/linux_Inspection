"""inspect/config.py — 配置层与阈值分层合并（T-102）。

职责（docs/specs/technical-design.md §4 config.py 行 + §6 配置设计）：
  - inspect.yml 加载（TD §6.3 配置边界：out_dir / inventory / profiles）；
  - 文档基线阈值加载：inspect/data/thresholds/linux-common-p0-v1.yaml
    （local-metrics-requirements.md §6 汇总表逐项转写，禁止发明阈值）；
  - 外部配置 override（thresholds-override.yml）加载与 threshold-override-v1
    schema 语义校验（TD §6.2 / §7.2；拒绝未知 status/op、缺 note、
    双重判定 op+value 与 range 同时出现）；
  - 阈值分层合并（MR §3 / HR §4 固定顺序：外部配置 > 文档基线 > UNKNOWN），
    输出每指标的 resolved 阈值与 provenance（config_sources / doc_sources /
    notes，HR §3 字段）。

错误处理（TD §6.2 / cli-contract §4）：任何配置解析/校验失败抛 ConfigError，
调用方（cli 编排）映射为执行失败退出码 10（EXIT_CONFIG_ERROR）。

依赖与实现说明：
  - 纯标准库实现。本项目未声明 PyYAML 运行时依赖（requirements.txt 仅
    xlsxwriter），jsonschema 为 dev 依赖（requirements-dev.txt）且环境未安装；
    本任务禁止安装依赖，因此 YAML 解析（严格子集）与 override 校验均为
    内置实现，语义与 inspect/schema/threshold-override-v1.schema.json 一致
    （该文件供外部 jsonschema 等校验器机器执行）。
  - YAML 子集：块映射（缩进）、块序列（- 项）、单行 flow 映射/序列
    （{k: v, ...} / [a, b, ...]）、# 注释、标量（引号字符串 / plain /
    整数 / 浮点 / true / false / null / ~）。不支持：多行字符串（| >）、
    锚点/别名、多文档、制表符缩进。文档基线文件与 override 文件均限本子集。

模块边界（TD §4）：只读配置文件；不执行采集命令、不做业务状态判定
（T-104 normalize）、不渲染；不导入本包其他模块（cli 等下游以
`import inspect.config` 单向依赖本模块）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# cli-contract §4 / TD §6.2：配置错误属执行失败（与业务状态无关）
EXIT_CONFIG_ERROR = 10

# 文档基线版本标识（MR §3 / §6：linux-common-p0-v1）
DOC_BASELINE_VERSION = "linux-common-p0-v1"

# Nginx 中间件文档基线版本（安徽农金Nginx、Keepalived运维巡检手册v1.0）
NGINX_BASELINE_VERSION = "nginx-p0-v1"

# Keepalived 中间件文档基线版本（同一份 Nginx/Keepalived 巡检手册）
KEEPALIVED_BASELINE_VERSION = "keepalived-p0-v1"

# Elasticsearch 运维巡检手册 P0/P1 基线版本
ELASTICSEARCH_BASELINE_VERSION = "elasticsearch-p0-p1-v1"

# 包内数据/模式文件（相对本模块定位，随包分发）
BASELINE_FILE = (
    Path(__file__).resolve().parent / "data" / "thresholds" / "linux-common-p0-v1.yaml"
)
NGINX_BASELINE_FILE = (
    Path(__file__).resolve().parent / "data" / "thresholds" / "nginx-p0-v1.yaml"
)
KEEPALIVED_BASELINE_FILE = (
    Path(__file__).resolve().parent / "data" / "thresholds" / "keepalived-p0-v1.yaml"
)
ELASTICSEARCH_BASELINE_FILE = (
    Path(__file__).resolve().parent / "data" / "thresholds" / "elasticsearch-p0-p1-v1.yaml"
)
OVERRIDE_SCHEMA_FILE = (
    Path(__file__).resolve().parent / "schema" / "threshold-override-v1.schema.json"
)

# 仓库根默认配置文件名（TD §6.3 / §6.2）
DEFAULT_INSPECT_CONFIG_NAME = "inspect.yml"
DEFAULT_OVERRIDE_NAME = "thresholds-override.yml"

# 状态集合
BASELINE_STATUSES = ("OK", "WARN", "CRIT", "UNKNOWN")
OVERRIDE_STATUSES = ("OK", "WARN", "CRIT")
OVERRIDE_OPS = (">", ">=", "<", "<=", "==", "!=")
UNKNOWN_REASONS = ("missing", "conflict", "none")

# 阈值层（HR §3 threshold.layer 枚举子集）
LAYER_DOCUMENT_BASELINE = "document-baseline"
LAYER_EXTERNAL_CONFIG = "external-config"
LAYER_UNRESOLVED = "unresolved-document-conflict"


class ConfigError(Exception):
    """配置错误（YAML 解析失败、schema 校验失败、结构/类型错误）。

    TD §6.2：配置错误按执行失败处理（cli-contract §4 退出码 10）。
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_CONFIG_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------
# 严格 YAML 子集解析器（纯标准库）
# --------------------------------------------------------------------------


class _YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    """去除行尾注释（# 前为行首或空白时起注释；引号内不处理）。"""
    quote = None
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote is None:
            if ch in "\"'":
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i].rstrip()
        else:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        i += 1
    return line.rstrip()


def _scalar_type(text: str) -> Any:
    """标量类型化：null/布尔/整数/浮点；其余为字符串。"""
    t = text.strip()
    if t in ("", "null", "Null", "NULL", "~"):
        return None
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?[0-9]+", t):
        return int(t)
    if re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", t):
        return float(t)
    return t


def _read_quoted(line: str, start: int, lineno: int, source: str) -> Tuple[Any, int]:
    """解析 line[start] 起的引号字符串（'…' 或 "…"），返回 (值, 结束下标)。"""
    q = line[start]
    i = start + 1
    n = len(line)
    out: List[str] = []
    while i < n:
        ch = line[i]
        # 单引号转义 '' 必须先行判定（否则被闭合检查截断）
        if q == "'" and ch == "'" and i + 1 < n and line[i + 1] == "'":
            out.append("'")
            i += 2
            continue
        if ch == q:
            return "".join(out), i + 1
        if q == '"' and ch == "\\":
            if i + 1 >= n:
                raise _YamlError(f"{source}:{lineno}: 转义符后无字符")
            nxt = line[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "\\":
                out.append("\\")
            elif nxt == '"':
                out.append('"')
            elif nxt == "u":
                hex4 = line[i + 2 : i + 6]
                if len(hex4) == 4:
                    try:
                        out.append(chr(int(hex4, 16)))
                    except ValueError as exc:
                        raise _YamlError(
                            f"{source}:{lineno}: 非法 \\u 转义 {hex4!r}"
                        ) from exc
                    i += 4
                else:
                    raise _YamlError(f"{source}:{lineno}: \\u 转义需 4 位十六进制")
            else:
                raise _YamlError(f"{source}:{lineno}: 不支持的转义 \\{nxt}")
            i += 2
            continue
        out.append(ch)
        i += 1
    raise _YamlError(f"{source}:{lineno}: 引号未闭合: {line!r}")


def _skip_ws(line: str, i: int) -> int:
    while i < len(line) and line[i] in " \t":
        i += 1
    return i


def _flow_value(line: str, i: int, lineno: int, source: str) -> Tuple[Any, int]:
    """解析单行 flow 上下文中的一个值（嵌套 {…}/[…]/引号/plain 标量）。"""
    n = len(line)
    if i >= n:
        raise _YamlError(f"{source}:{lineno}: flow 值缺失")
    ch = line[i]
    if ch in "\"'":
        return _read_quoted(line, i, lineno, source)
    if ch == "[":
        items: List[Any] = []
        j = _skip_ws(line, i + 1)
        if j < n and line[j] == "]":
            return items, j + 1
        while True:
            v, j = _flow_value(line, j, lineno, source)
            items.append(v)
            j = _skip_ws(line, j)
            if j >= n:
                raise _YamlError(f"{source}:{lineno}: flow 序列未闭合: {line!r}")
            if line[j] == "]":
                return items, j + 1
            if line[j] != ",":
                raise _YamlError(f"{source}:{lineno}: flow 序列缺少逗号: {line!r}")
            j = _skip_ws(line, j + 1)
            if j < n and line[j] == "]":
                raise _YamlError(f"{source}:{lineno}: flow 序列尾逗号（子集不支持）")
    if ch == "{":
        obj: Dict[Any, Any] = {}
        j = _skip_ws(line, i + 1)
        if j < n and line[j] == "}":
            return obj, j + 1
        while True:
            j = _skip_ws(line, j)
            if j >= n:
                raise _YamlError(f"{source}:{lineno}: flow 映射未闭合: {line!r}")
            key, j = _flow_key(line, j, lineno, source)
            j = _skip_ws(line, j)
            if j >= n or line[j] != ":":
                raise _YamlError(f"{source}:{lineno}: flow 映射键缺少冒号: {line!r}")
            j = _skip_ws(line, j + 1)
            if j >= n:
                raise _YamlError(f"{source}:{lineno}: flow 映射值缺失: {line!r}")
            value, j = _flow_value(line, j, lineno, source)
            if key in obj:
                raise _YamlError(f"{source}:{lineno}: flow 映射重复键 {key!r}")
            obj[key] = value
            j = _skip_ws(line, j)
            if j >= n:
                raise _YamlError(f"{source}:{lineno}: flow 映射未闭合: {line!r}")
            if line[j] == "}":
                return obj, j + 1
            if line[j] != ",":
                raise _YamlError(f"{source}:{lineno}: flow 映射缺少逗号: {line!r}")
            j = _skip_ws(line, j + 1)
    # plain 标量：到逗号/右括号为止
    j = i
    while j < n and line[j] not in ",}]":
        j += 1
    raw = line[i:j].strip()
    if raw == "":
        raise _YamlError(f"{source}:{lineno}: flow 中空标量: {line!r}")
    if ": " in raw:
        raise _YamlError(
            f"{source}:{lineno}: flow plain 标量含 ': '（请使用引号）: {raw!r}"
        )
    return _scalar_type(raw), j


def _flow_key(line: str, i: int, lineno: int, source: str) -> Tuple[Any, int]:
    if i < len(line) and line[i] in "\"'":
        return _read_quoted(line, i, lineno, source)
    j = i
    while j < len(line) and line[j] not in ":{},]":
        j += 1
    raw = line[i:j].strip()
    if raw == "":
        raise _YamlError(f"{source}:{lineno}: flow 键为空: {line!r}")
    return _scalar_type(raw), j


def _split_key(content: str, lineno: int, source: str) -> Tuple[Any, Optional[str]]:
    """拆分映射条目 `key: value`；无值（rest 为空）返回 (key, None)。"""
    quote = None
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if quote is not None:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 >= n or content[i + 1] in " \t"):
            key_raw = content[:i].strip()
            if key_raw == "":
                raise _YamlError(f"{source}:{lineno}: 空键: {content!r}")
            key = _scalar_type(key_raw)
            rest = content[i + 1 :].strip()
            if rest == "":
                return key, None
            return key, rest
        i += 1
    raise _YamlError(f"{source}:{lineno}: 映射条目缺少冒号: {content!r}")


def _parse_scalar_or_flow(rest: str, lineno: int, source: str) -> Any:
    if rest.startswith(("{", "[")):
        value, j = _flow_value(rest, 0, lineno, source)
        if j != len(rest):
            raise _YamlError(
                f"{source}:{lineno}: flow 值后有多余内容: {rest[j:]!r}"
            )
        return value
    if rest.startswith(("\"", "'")):
        value, j = _read_quoted(rest, 0, lineno, source)
        if j != len(rest):
            raise _YamlError(
                f"{source}:{lineno}: 引号字符串后有多余内容: {rest[j:]!r}"
            )
        return value
    if ": " in rest or rest.endswith(":") or "\t" in rest:
        raise _YamlError(
            f"{source}:{lineno}: plain 标量含 ': '（块级嵌套请用缩进，"
            f"内联映射请用 {{key: value}}）：{rest!r}"
        )
    return _scalar_type(rest)


def _parse_block(lines: List[Tuple[int, str, int]], idx: int, source: str) -> Tuple[Any, int]:
    """解析一个缩进块（映射或序列），返回 (值, 下一行下标)。"""
    indent, content, _lineno = lines[idx]
    if content == "-" or content.startswith("- "):
        return _parse_sequence(lines, idx, indent, source)
    return _parse_mapping(lines, idx, indent, source)


def _parse_mapping(
    lines: List[Tuple[int, str, int]], idx: int, block_indent: int, source: str
) -> Tuple[Dict[Any, Any], int]:
    obj: Dict[Any, Any] = {}
    i = idx
    while i < len(lines):
        indent, content, lineno = lines[i]
        if indent < block_indent:
            break
        if indent != block_indent:
            raise _YamlError(
                f"{source}:{lineno}: 缩进不一致（期望 {block_indent} 空格）: {content!r}"
            )
        key, rest = _split_key(content, lineno, source)
        if key in obj:
            raise _YamlError(f"{source}:{lineno}: 重复键 {key!r}")
        if rest is None:
            if i + 1 < len(lines) and lines[i + 1][0] > block_indent:
                obj[key], i = _parse_block(lines, i + 1, source)
            else:
                obj[key] = None
                i += 1
        else:
            obj[key] = _parse_scalar_or_flow(rest, lineno, source)
            i += 1
    return obj, i


def _parse_sequence(
    lines: List[Tuple[int, str, int]], idx: int, block_indent: int, source: str
) -> Tuple[List[Any], int]:
    items: List[Any] = []
    i = idx
    while i < len(lines):
        indent, content, lineno = lines[i]
        if indent < block_indent:
            break
        if indent != block_indent or not (content == "-" or content.startswith("- ")):
            raise _YamlError(
                f"{source}:{lineno}: 序列项格式错误（应为 '- 项'）: {content!r}"
            )
        rest = content[1:].strip()
        if rest == "":
            if i + 1 < len(lines) and lines[i + 1][0] > block_indent:
                val, i = _parse_block(lines, i + 1, source)
                items.append(val)
            else:
                items.append(None)
                i += 1
        else:
            items.append(_parse_scalar_or_flow(rest, lineno, source))
            i += 1
    return items, i


def _parse_yaml_text(text: str, source: str) -> Any:
    """解析 YAML 子集文档 → dict/list/标量。"""
    lines: List[Tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if lineno == 1 and raw.startswith("﻿"):
            raw = raw[1:]
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise _YamlError(f"{source}:{lineno}: 缩进使用制表符（子集不支持）")
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped[indent:].strip(), lineno))
    if not lines:
        return None
    value, consumed = _parse_block(lines, 0, source)
    if consumed != len(lines):
        raise _YamlError(
            f"{source}: 文档尾部存在未解析内容（第 {lines[consumed][2]} 行）"
        )
    return value


def _read_yaml_file(path: Union[str, Path]) -> Any:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"配置文件无法读取: {path}（{exc}）") from exc
    try:
        return _parse_yaml_text(text, source=str(path))
    except _YamlError as exc:
        raise ConfigError(str(exc)) from exc


# --------------------------------------------------------------------------
# inspect.yml（TD §6.3）
# --------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_inspect_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """加载 inspect.yml（TD §6.3 配置边界）。

    - path=None：默认仓库根 <root>/inspect.yml；文件不存在 → 返回默认配置
      （out_dir=out、inventory=None、profiles={}），inspect.yml 为可选配置；
    - path 显式给出：文件必须存在且可解析（缺失/错误 → ConfigError）；
    - 未知顶层字段、schema/version 不匹配、字段类型错误 → ConfigError。

    返回：{"schema", "version", "out_dir", "inventory", "profiles"}。
    """
    if path is None:
        candidate = _repo_root() / DEFAULT_INSPECT_CONFIG_NAME
        if not candidate.is_file():
            return {
                "schema": "inspect-config-v1",
                "version": 1,
                "out_dir": "out",
                "inventory": None,
                "profiles": {},
            }
        path = candidate

    data = _read_yaml_file(path)
    if not isinstance(data, dict):
        raise ConfigError(f"inspect.yml 顶层应为映射: {path}")

    allowed = {"schema", "version", "out_dir", "inventory", "profiles"}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"inspect.yml 未知字段: {sorted(unknown)}: {path}")

    if "schema" in data and data["schema"] != "inspect-config-v1":
        raise ConfigError(f"inspect.yml schema 不匹配（期望 inspect-config-v1）: {path}")
    if "version" in data and data["version"] != 1:
        raise ConfigError(f"inspect.yml version 不匹配（期望 1）: {path}")

    out_dir = data.get("out_dir", "out")
    if not isinstance(out_dir, str) or not out_dir.strip():
        raise ConfigError(f"inspect.yml out_dir 必须为非空字符串: {path}")

    inventory = data.get("inventory", None)
    if inventory is not None and not isinstance(inventory, str):
        raise ConfigError(f"inspect.yml inventory 必须为字符串或 null: {path}")

    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f"inspect.yml profiles 必须为映射: {path}")
    for name, prof in profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"inspect.yml profiles 键必须为非空字符串: {path}")
        if not isinstance(prof, dict):
            raise ConfigError(f"inspect.yml profiles.{name} 必须为映射: {path}")

    return {
        "schema": "inspect-config-v1",
        "version": 1,
        "out_dir": out_dir,
        "inventory": inventory,
        "profiles": profiles,
    }


# --------------------------------------------------------------------------
# 文档基线（MR §6 转写，禁止发明阈值）
# --------------------------------------------------------------------------


def load_document_baseline(
    path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """加载文档基线阈值 linux-common-p0-v1.yaml（MR §6 逐项转写）。

    path=None → 包内 data/thresholds/linux-common-p0-v1.yaml。
    结构校验：schema/version 标识、metrics 非空映射；每指标 name /
    source_anchor / boundaries（OK/WARN/CRIT/UNKNOWN 四层）完整；
    定义层 rule + rule_id（版本前缀），未定义层 rule=null + reason
    （missing|conflict|none）+ note。

    返回：metric_id → {
      metric_id, name, version, source_anchor, layer("document-baseline"),
      boundaries: {OK: {rule, rule_id, reason, note}, WARN: …, CRIT: …, UNKNOWN: …}
    }（顺序与文件一致）。
    """
    if path is None:
        path = BASELINE_FILE
    data = _read_yaml_file(path)
    if not isinstance(data, dict):
        raise ConfigError(f"文档基线顶层应为映射: {path}")
    if data.get("schema") != "threshold-baseline-v1":
        raise ConfigError(f"文档基线 schema 不匹配（期望 threshold-baseline-v1）: {path}")
    if data.get("version") != DOC_BASELINE_VERSION:
        raise ConfigError(
            f"文档基线 version 不匹配（期望 {DOC_BASELINE_VERSION}）: {path}"
        )
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"文档基线 metrics 必须为非空映射: {path}")

    result: Dict[str, Dict[str, Any]] = {}
    for metric_id, spec in metrics.items():
        result[metric_id] = _validate_baseline_metric(metric_id, spec, path)
    return result


def load_nginx_baseline(
    path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """加载 Nginx 文档基线阈值 nginx-p0-v1.yaml（巡检手册转写）。

    结构校验与 load_document_baseline 一致，仅版本标识使用
    NGINX_BASELINE_VERSION（nginx-p0-v1），rule_id 前缀随之不同。
    """
    if path is None:
        path = NGINX_BASELINE_FILE
    data = _read_yaml_file(path)
    if not isinstance(data, dict):
        raise ConfigError(f"Nginx 文档基线顶层应为映射: {path}")
    if data.get("schema") != "threshold-baseline-v1":
        raise ConfigError(
            f"Nginx 文档基线 schema 不匹配（期望 threshold-baseline-v1）: {path}"
        )
    if data.get("version") != NGINX_BASELINE_VERSION:
        raise ConfigError(
            f"Nginx 文档基线 version 不匹配（期望 {NGINX_BASELINE_VERSION}）: {path}"
        )
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"Nginx 文档基线 metrics 必须为非空映射: {path}")

    result: Dict[str, Dict[str, Any]] = {}
    for metric_id, spec in metrics.items():
        result[metric_id] = _validate_baseline_metric(
            metric_id, spec, path, version=NGINX_BASELINE_VERSION
        )
    return result


def _validate_baseline_metric(
    metric_id: Any,
    spec: Any,
    path: Union[str, Path],
    version: str = DOC_BASELINE_VERSION,
) -> Dict[str, Any]:
    if not isinstance(metric_id, str) or not re.fullmatch(r"local\.[a-z0-9_.]+", metric_id):
        raise ConfigError(f"文档基线 metric_id 非法: {metric_id!r}: {path}")
    if not isinstance(spec, dict):
        raise ConfigError(f"文档基线 {metric_id} 定义必须为映射: {path}")

    allowed = {"name", "source_anchor", "boundaries"}
    unknown = set(spec) - allowed
    if unknown:
        raise ConfigError(f"文档基线 {metric_id} 未知字段: {sorted(unknown)}: {path}")

    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"文档基线 {metric_id} name 必须为非空字符串: {path}")
    anchor = spec.get("source_anchor")
    if not isinstance(anchor, str) or not anchor.strip():
        raise ConfigError(f"文档基线 {metric_id} source_anchor 必须为非空字符串: {path}")

    boundaries = spec.get("boundaries")
    if not isinstance(boundaries, dict):
        raise ConfigError(f"文档基线 {metric_id} boundaries 必须为映射: {path}")
    if set(boundaries) != set(BASELINE_STATUSES):
        raise ConfigError(
            f"文档基线 {metric_id} boundaries 必须恰好含 {BASELINE_STATUSES}: {path}"
        )

    levels: Dict[str, Dict[str, Any]] = {}
    slug = metric_id.split(".", 1)[1]
    for status in BASELINE_STATUSES:
        entry = boundaries[status]
        if not isinstance(entry, dict):
            raise ConfigError(f"文档基线 {metric_id} boundaries.{status} 必须为映射: {path}")
        rule = entry.get("rule")
        rule_id = entry.get("rule_id")
        reason = entry.get("reason")
        note = entry.get("note")
        if rule is not None:
            if not isinstance(rule, str) or not rule.strip():
                raise ConfigError(f"文档基线 {metric_id} boundaries.{status} rule 非法: {path}")
            expected_id = f"{version}.{slug}.{status.lower()}"
            if rule_id != expected_id:
                raise ConfigError(
                    f"文档基线 {metric_id} boundaries.{status} rule_id 应等于 {expected_id}: "
                    f"{rule_id!r}: {path}"
                )
            levels[status] = {"rule": rule, "rule_id": rule_id, "reason": None, "note": None}
        else:
            if rule_id is not None:
                raise ConfigError(
                    f"文档基线 {metric_id} boundaries.{status} rule=null 时 rule_id 必须为 null: {path}"
                )
            if reason not in UNKNOWN_REASONS:
                raise ConfigError(
                    f"文档基线 {metric_id} boundaries.{status} reason 非法"
                    f"（期望 {UNKNOWN_REASONS}）: {reason!r}: {path}"
                )
            if not isinstance(note, str) or not note.strip():
                raise ConfigError(
                    f"文档基线 {metric_id} boundaries.{status} note 必须为非空字符串: {path}"
                )
            levels[status] = {"rule": None, "rule_id": None, "reason": reason, "note": note}

    return {
        "metric_id": metric_id,
        "name": name,
        "version": version,
        "source_anchor": anchor,
        "boundaries": levels,
        "layer": LAYER_DOCUMENT_BASELINE,
    }


# --------------------------------------------------------------------------
# thresholds-override.yml（TD §6.2 / §7.2 schema 语义校验）
# --------------------------------------------------------------------------


def validate_override_document(data: Any, source: str = "<override>") -> Dict[str, Any]:
    """按 threshold-override-v1 schema 语义校验 override 文档并规范化。

    必须拒绝（合同/合同 mitigation）：
      - 未知 status（仅 OK/WARN/CRIT）、未知 op（仅 > >= < <= == !=）；
      - 缺 note（必填，回填 provenance.notes）；
      - 双重判定（op+value 与 range 同时出现）；
      - 未知字段、类型错误、空 rules、非 ^local\\. 指标键、schema/version 不匹配。

    返回规范化文档：
      {"schema", "version", "scope", "hosts",
       "metrics": {metric_id: {"rules": [{status, op, value, range, note}]}}}
    （op/value 或 range 未使用的一侧为 None；scope/hosts 缺省为 None。）
    """
    if not isinstance(data, dict):
        raise ConfigError(f"override 顶层应为映射: {source}")

    allowed_top = {"schema", "version", "scope", "hosts", "metrics"}
    unknown = set(data) - allowed_top
    if unknown:
        raise ConfigError(f"override 未知字段: {sorted(unknown)}: {source}")
    if data.get("schema") != "threshold-override-v1":
        raise ConfigError(f"override schema 不匹配（期望 threshold-override-v1）: {source}")
    if data.get("version") != 1:
        raise ConfigError(f"override version 不匹配（期望 1）: {source}")

    scope = data.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise ConfigError(f"override scope 必须为字符串或 null: {source}")
    hosts = data.get("hosts")
    if hosts is not None and (
        not isinstance(hosts, list) or any(not isinstance(h, str) for h in hosts)
    ):
        raise ConfigError(f"override hosts 必须为字符串数组或 null: {source}")

    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"override metrics 必须为非空映射: {source}")

    out_metrics: Dict[str, Dict[str, Any]] = {}
    for metric_id, ov in metrics.items():
        if not isinstance(metric_id, str) or not re.fullmatch(r"local\.[a-z0-9_.]+", metric_id):
            raise ConfigError(f"override 指标键必须匹配 ^local\\.: {metric_id!r}: {source}")
        if not isinstance(ov, dict):
            raise ConfigError(f"override {metric_id} 必须为映射: {source}")
        unknown_fields = set(ov) - {"rules"}
        if unknown_fields:
            raise ConfigError(f"override {metric_id} 未知字段: {sorted(unknown_fields)}: {source}")
        if "rules" not in ov:
            raise ConfigError(f"override {metric_id} 缺少 rules: {source}")
        rules = ov["rules"]
        if not isinstance(rules, list) or not rules:
            raise ConfigError(f"override {metric_id} rules 必须为非空数组: {source}")
        out_rules = [
            _validate_override_rule(rule, f"{source} {metric_id} rules[{i}]")
            for i, rule in enumerate(rules, 1)
        ]
        out_metrics[metric_id] = {"rules": out_rules}

    return {
        "schema": "threshold-override-v1",
        "version": 1,
        "scope": scope,
        "hosts": hosts,
        "metrics": out_metrics,
    }


def _validate_override_rule(rule: Any, where: str) -> Dict[str, Any]:
    if not isinstance(rule, dict):
        raise ConfigError(f"override 规则必须为映射: {where}")

    allowed = {"status", "op", "value", "range", "note"}
    unknown = set(rule) - allowed
    if unknown:
        raise ConfigError(f"override 规则未知字段: {sorted(unknown)}: {where}")

    status = rule.get("status")
    if status not in OVERRIDE_STATUSES:
        raise ConfigError(
            f"override 规则 status 非法（期望 OK/WARN/CRIT）: {status!r}: {where}"
        )

    note = rule.get("note")
    if not isinstance(note, str) or not note.strip():
        raise ConfigError(f"override 规则缺 note（必填，回填 provenance.notes）: {where}")

    op = rule.get("op")
    value = rule.get("value")
    range_ = rule.get("range")
    has_expr = op is not None or value is not None
    has_range = range_ is not None

    if has_expr and has_range:
        raise ConfigError(
            f"override 规则双重判定（op+value 与 range 互斥，TD §6.2 oneOf）: {where}"
        )
    if has_expr:
        if op not in OVERRIDE_OPS:
            raise ConfigError(
                f"override 规则 op 非法（期望 {OVERRIDE_OPS}）: {op!r}: {where}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"override 规则 value 必须为数值: {value!r}: {where}")
        return {
            "status": status,
            "op": op,
            "value": float(value),
            "range": None,
            "note": note,
        }
    if has_range:
        if not isinstance(range_, list) or len(range_) != 2:
            raise ConfigError(
                f"override 规则 range 必须为 [min, max] 两元素数组: {where}"
            )
        for item in range_:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ConfigError(f"override 规则 range 元素必须为数值: {where}")
        return {
            "status": status,
            "op": None,
            "value": None,
            "range": [float(range_[0]), float(range_[1])],
            "note": note,
        }
    raise ConfigError(
        f"override 规则缺少判定表达式（op+value 或 range 二选一，TD §6.2 oneOf）: {where}"
    )


def load_override(path: Union[str, Path]) -> Dict[str, Any]:
    """加载并校验 thresholds-override.yml（threshold-override-v1 schema 语义）。"""
    data = _read_yaml_file(path)
    return validate_override_document(data, source=str(path))


# --------------------------------------------------------------------------
# 阈值分层合并（外部配置 > 文档基线 > UNKNOWN；HR §4 固定顺序）
# --------------------------------------------------------------------------


def build_resolved_thresholds(
    baseline: Optional[Dict[str, Dict[str, Any]]] = None,
    override: Optional[Union[Dict[str, Any], str, Path]] = None,
    override_source: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """阈值分层合并（MR §3 / HR §4：外部配置 > 文档基线 > UNKNOWN）。

    - baseline：load_document_baseline() 结果，或 None（自动加载默认基线文件）；
    - override：load_override() 结果（校验后的字典）、override 文件路径
      （str/Path，自动加载）或 None（无外部配置 → 全部走文档基线）；
    - override_source：provenance.config_sources 记录的外部配置来源
      （缺省为 override 路径字符串或 "<external-config>"）。

    返回：metric_id → {
      metric_id, version, layer, rules, unknown, provenance
    }，顺序 = 基线文件顺序 + 仅 override 出现的指标。

    - layer=external-config：rules 为 override 规则（按声明顺序，首个匹配
      生效，TD §6.2）；provenance.config_sources 记录来源；
    - layer=document-baseline：rules 为该指标 OK/WARN/CRIT 中已定义边界
      （{status, rule, rule_id}），provenance.doc_sources 记录来源锚点；
      unknown 为该指标 UNKNOWN 边界（reason/note）；
    - layer=unresolved-document-conflict：文档基线未定义任何边界
      （本基线文件 10 指标均有 OK 边界，此分支仅防御）。
    """
    if baseline is None:
        # Default baseline merges the Linux common P0 file and the Nginx
        # middleware file so both document-baseline layers resolve together.
        baseline = {}
        baseline.update(load_document_baseline())
        baseline.update(load_nginx_baseline())
        baseline.update(load_keepalived_baseline())
        baseline.update(load_elasticsearch_baseline())
        # Additional middleware facts are catalog-driven.  Their manual rows
        # often describe the healthy/error evidence but do not give numeric
        # WARN/CRIT cut-offs, so use an explicit product-supplement baseline
        # and retain the catalog anchor as provenance.
        try:
            from inspect import metrics as metrics_catalog
            for metric in metrics_catalog.METRICS:
                if (
                    metric.get("parser") != "parse_middleware_text"
                    and not metric.get("metric_id", "").startswith((
                        "local.kafka.", "local.mysql.", "local.nacos.",
                        "local.rabbitmq.", "local.redis.", "local.rocketmq.",
                        "local.tomcat.", "local.zookeeper.",
                        "local.keepalived.vip.present",
                        "local.keepalived.vrrp.role",
                        "local.keepalived.health_check.status",
                    ))
                ):
                    continue
                metric_id = metric["metric_id"]
                baseline.setdefault(metric_id, {
                    "name": metric["name"],
                    "source_anchor": metric["source_anchor"],
                    "boundaries": {
                        "OK": {"rule": "命令输出无明确异常标记 → OK", "rule_id": f"{metric_id}:supplement.ok", "reason": None, "note": "产品补充阈值"},
                        "WARN": {"rule": "命令输出含告警/积压/偏离证据 → WARN", "rule_id": f"{metric_id}:supplement.warn", "reason": None, "note": "产品补充阈值"},
                        "CRIT": {"rule": "命令输出含故障/不可用/严重错误证据 → CRIT", "rule_id": f"{metric_id}:supplement.crit", "reason": None, "note": "产品补充阈值"},
                        "UNKNOWN": {"rule": None, "rule_id": None, "reason": "missing", "note": metric.get("unknown_conditions")},
                    },
                })
        except ImportError:
            pass

    if override is None:
        override_doc: Dict[str, Any] = {}
        resolved_source: Optional[str] = None
    elif isinstance(override, (str, Path)):
        resolved_source = str(override)
        override_doc = load_override(override)
    else:
        resolved_source = override_source or "<external-config>"
        override_doc = validate_override_document(override, source=resolved_source)

    override_metrics = override_doc.get("metrics", {})
    result: Dict[str, Dict[str, Any]] = {}
    for metric_id, spec in baseline.items():
        result[metric_id] = _resolve_one(
            metric_id, spec, override_metrics.get(metric_id), resolved_source
        )
    for metric_id in override_metrics:
        if metric_id not in result:
            result[metric_id] = _resolve_one(
                metric_id, None, override_metrics[metric_id], resolved_source
            )
    return result


def _resolve_one(
    metric_id: str,
    baseline_spec: Optional[Dict[str, Any]],
    override_ov: Optional[Dict[str, Any]],
    override_source: Optional[str],
) -> Dict[str, Any]:
    if override_ov is not None:
        rules = [dict(r) for r in override_ov["rules"]]
        notes = [r["note"] for r in rules]
        return {
            "metric_id": metric_id,
            "version": DOC_BASELINE_VERSION,
            "layer": LAYER_EXTERNAL_CONFIG,
            "rules": rules,
            "unknown": {"reason": "none", "note": None},
            "provenance": {
                "config_sources": [override_source] if override_source else [],
                "doc_sources": (
                    [baseline_spec["source_anchor"]] if baseline_spec else []
                ),
                "notes": "；".join(notes) if notes else None,
            },
        }

    if baseline_spec is not None:
        defined: List[Dict[str, Any]] = []
        for status in ("OK", "WARN", "CRIT"):
            entry = baseline_spec["boundaries"][status]
            if entry["rule"] is not None:
                defined.append(
                    {"status": status, "rule": entry["rule"], "rule_id": entry["rule_id"]}
                )
        unknown = dict(baseline_spec["boundaries"]["UNKNOWN"])
        return {
            "metric_id": metric_id,
            "version": baseline_spec.get("version") or DOC_BASELINE_VERSION,
            "layer": LAYER_DOCUMENT_BASELINE if defined else LAYER_UNRESOLVED,
            "rules": defined,
            "unknown": unknown,
            "provenance": {
                "config_sources": [],
                "doc_sources": [baseline_spec["source_anchor"]],
                "notes": None,
            },
        }

    raise ConfigError(f"无法解析指标阈值（无文档基线、无外部配置）: {metric_id}")


# --------------------------------------------------------------------------
# inspect.conf（所有中间件的运行默认配置）
# --------------------------------------------------------------------------

DEFAULT_RUNTIME_CONFIG_NAME = "inspect.conf"

# 现场连接、命令和 HTTP 请求的统一默认上限（秒）。inspect.conf 可覆盖，
# 但 CLI 会把同一个值传给 SSH、探测/指标 shell 和 curl，避免各模块各自等待。
DEFAULT_INSPECT_TIMEOUT_SEC = 3
MIN_INSPECT_TIMEOUT_SEC = 1
MAX_INSPECT_TIMEOUT_SEC = 60

# inspect.conf 使用一行一个参数、管道分隔候选值；这里的空字典表示“没有
# 配置候选路径”，不是再回退到文档中的固定路径。这样能保证现场没有配置时
# 的中间件指标进入 UNKNOWN，而不是误检另一套安装。
INSPECT_CONF_EMPTY_DEFAULTS: Dict[str, List[str]] = {
    "timeout": [str(DEFAULT_INSPECT_TIMEOUT_SEC)],
    "nginx_bin": [],
    "nginx_conf": [],
    "nginx_log": [],
    "nginx_error_log": [],
    "nginx_access_log": [],
    "nginx_port": [],
    "nginx_version": [],
    "nginx_baseline": [],
    "nginx_whitelist": [],
    "keepalived_bin": [],
    "keepalived_conf": [],
    "keepalived_log": [],
    "keepalived_healthcheck_script": ["/etc/keepalived/check.sh"],
    "keepalived_vip": [],
    "keepalived_port": [],
    "keepalived_version": [],
    "keepalived_baseline": [],
    "keepalived_whitelist": [],
    "elasticsearch_bin": [],
    "elasticsearch_conf": [],
    "elasticsearch_log": [],
    "elasticsearch_gc_log": [],
    "elasticsearch_data": [],
    "elasticsearch_backup": [],
    "elasticsearch_endpoint": [],
    "elasticsearch_http_port": [],
    "elasticsearch_transport_port": [],
    "elasticsearch_version": [],
    "elasticsearch_expected_nodes": [],
    "elasticsearch_seed_hosts": [],
    "elasticsearch_system_user": [],
    "elasticsearch_auth_file": [],
    "elasticsearch_api_user": [],
    "elasticsearch_api_password": [],
    "elasticsearch_cacert": [],
    "elasticsearch_cert": [],
    "elasticsearch_snapshot_repo": [],
    "elasticsearch_whitelist": [],
    # Kafka/Zookeeper
    "kafka_bin": ["/opt/kafka/bin/kafka-server-start.sh"],
    "kafka_conf": ["/opt/kafka/conf/server.properties"],
    "kafka_zookeeper_conf": ["/opt/zookeeper/conf/zoo.cfg"],
    "zookeeper_bin": ["/opt/redis/bin/redis-server"],
    "zookeeper_conf": ["/opt/zookeeper/conf/zoo.cfg"],
    "zookeeper_log": ["/opt/zookeeper/logs"],
    "zookeeper_data": ["/opt/zookeeper/data"],
    "zookeeper_datalog": ["/opt/zookeeper/datalog"],
    "kafka_log": ["/opt/kafka/logs/"],
    "kafka_zookeeper_connect": ["127.0.0.1:2181"],
    "kafka_bootstrap": ["127.0.0.1:9093"],
    "kafka_ssl_config": ["/opt/kafka/config/client.properties"],
    "kafka_port": ["9093"],
    "kafka_zookeeper_port": ["2181"],
    "zookeeper_client_port": ["2181"],
    "zookeeper_peer_port": ["2888"],
    "zookeeper_election_port": ["3888"],
    # MySQL
    "mysql_bin": ["/opt/mysql/bin/mysql"],
    "mysql_conf": ["/opt/mysql/conf/my.cnf"],
    "mysql_socket": ["/opt/mysql/tmp/mysql.sock"],
    "mysql_log": ["/opt/mysql/logs"],
    "mysql_error_log": ["/opt/mysql/logs/error.log"],
    "mysql_slow_log": ["/opt/mysql/logs/slow.log"],
    "mysql_data": ["/opt/mysql/data"],
    "mysql_binlog": ["/opt/mysql/binlog"],
    "mysql_relaylog": ["/opt/mysql/relaylog"],
    "mysql_backup": ["/opt/mysql/backuptest"],
    "mysql_port": ["3306"],
    "mysql_user": ["Mysql_inspect"],
    "mysql_passwd": ["CHANGE_ME"],
    "mysql_host": ["127.0.0.1"],
    # Nacos
    "nacos_home": ["/opt/nacos"],
    "nacos_bin": ["/opt/nacos/bin/startup.sh"],
    "nacos_conf": ["/opt/nacos/conf/application.properties"],
    "nacos_cluster_conf": ["/opt/nacos/conf/cluster.conf"],
    "nacos_data": ["/opt/nacos/data"],
    "nacos_endpoint": ["http://127.0.0.1:8848"],
    "nacos_http_port": ["8848"],
    "nacos_grpc_port": ["9848"],
    "nacos_grpc_port_offset": ["9849"],
    "nacos_raft_port": ["7848"],
    "nacos_log": ["/opt/nacos/logs"],
    "nacos_expected_nodes": ["3"],
    "nacos_user": ["nacos"],
    "nacos_passwd": ["CHANGE_ME"],
    # RabbitMQ
    "rabbitmq_home": ["/opt/rabbitmq"],
    "rabbitmq_bin": ["/opt/rabbitmq/sbin/rabbitmq-server"],
    "rabbitmq_conf": ["/opt/rabbitmq/conf/rabbitmq.conf"],
    "rabbitmq_env_conf": ["/opt/rabbitmq/conf/rabbitmq-env.conf"],
    "rabbitmq_log": ["/opt/rabbitmq/logs"],
    "rabbitmq_data": ["/opt/rabbitmq/data/mnesia"],
    "rabbitmq_run": ["/opt/rabbitmq/run"],
    "rabbitmq_cookie": ["/home/rabbitmq/.erlang.cookie"],
    "rabbitmq_user": ["rabbitmq"],
    "rabbitmq_unit": ["rabbitmq"],
    "rabbitmq_expected_nodes": ["3"],
    "rabbitmq_port": ["5672"],
    "rabbitmq_management_port": ["15672"],
    "rabbitmq_cluster_port": ["25672"],
    "rabbitmq_epmd_port": ["4369"],
    # Redis
    "redis_home": ["/opt/redis"],
    "redis_bin": ["/opt/redis/bin/redis-server"],
    "redis_conf": ["/opt/redis/conf"],
    "redis_log": ["/opt/redis/logs"],
    "redis_data": ["/opt/redis/data"],
    "redis_pid": ["/opt/redis/pid"],
    "redis_user": ["redis"],
    "redis_passwd": ["CHANGE_ME"],
    "redis_version": ["7.4.2"],
    "redis_mode": ["cluster"],
    "redis_host": ["127.0.0.1"],
    "redis_port": ["6379"],
    "redis_replica_port": ["16379"],
    "redis_sentinel_port": ["26379"],
    "redis_cluster_port": ["7000"],
    "redis_cluster_bus_port": ["17000"],
    "redis_expected_masters": ["3"],
    "redis_expected_replicas": ["3"],
    "redis_expected_sentinels": ["3"],
    # RocketMQ
    "rocketmq_home": ["/opt/rocketmq"],
    "rocketmq_jdk_home": ["/opt/jdk1.8.0_421"],
    "rocketmq_profile": ["/home/rocketmq/.bash_profile"],
    "rocketmq_mode": ["cluster"],
    "rocketmq_bin": ["/opt/rocketmq/bin/mqnamesrv"],
    "rocketmq_conf": ["/opt/rocketmq/conf"],
    "rocketmq_log": ["/opt/rabbitmq/logs"],
    "rocketmq_broker_conf": ["/opt/rocketmq/conf/broker.conf"],
    "rocketmq_namesrv_conf": ["/opt/rocketmq/conf/namesrv.properties"],
    "rocketmq_namesrv_port": ["9876"],
    "rocketmq_controller_port": ["9877"],
    "rocketmq_broker_port": ["10911"],
    "rocketmq_broker_ha_port": ["10912"],
    "rocketmq_namesrv_addr": ["127.0.0.1:9876"],
    "rocketmq_controller_addr": ["127.0.0.1:9877"],
    "rocketmq_broker": ["broker-a"],
    "rocketmq_expected_nodes": ["3"],
    "rocketmq_expected_sync_replicas": ["2"],
    "rocketmq_old_log_days": ["30"],
    # Tomcat
    "tomcat_home": ["/opt/tomcat"],
    "tomcat_conf": ["/opt/tomcat/conf"],
    "tomcat_bin": ["/opt/tomcat/bin"],
    "tomcat_log": ["/opt/tomcat/logs"],
    "tomcat_port": ["8080"],
    "tomcat_https_port": ["8443"],
    "tomcat_shutdown_port": ["8005"],
    "tomcat_user": ["tomcat"],
    "tomcat_java_home": ["/opt/jre1.8.0_421"],
    "tomcat_version": ["9.0.110"],
    "tomcat_webapps": ["/opt/tomcat/webapps"],
    "tomcat_old_log_days": ["1"],
    "tomcat_large_log_size": ["1G"],
}

_CONF_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _split_conf_values(value: str, *, source: str, lineno: int) -> List[str]:
    """拆分 inspect.conf 的 `value1|value2`，支持每段用单/双引号包裹。"""
    values: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    escaped = False
    for char in value.strip():
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "|":
            item = "".join(current).strip()
            if not item:
                raise ConfigError(f"inspect.conf 第 {lineno} 行存在空候选值: {source}")
            values.append(item)
            current = []
        else:
            current.append(char)
    if escaped or quote is not None:
        raise ConfigError(f"inspect.conf 第 {lineno} 行引号/转义未闭合: {source}")
    item = "".join(current).strip()
    if not item:
        raise ConfigError(f"inspect.conf 第 {lineno} 行值为空: {source}")
    values.append(item)
    return values


def _ensure_private_runtime_config(path: Path) -> None:
    """确保现场运行配置不是组/其他用户可读写（Linux 要求 700）。"""
    if os.name == "nt":
        return
    try:
        mode = path.stat().st_mode & 0o777
        if mode != 0o700:
            path.chmod(0o700)
        if path.stat().st_mode & 0o077:
            raise ConfigError(f"inspect.conf 权限必须为 700: {path}")
    except OSError as exc:
        raise ConfigError(f"inspect.conf 权限无法设置为 700: {path}（{exc}）") from exc


def load_inspect_conf(path: Optional[Union[str, Path]] = None) -> Dict[str, List[str]]:
    """加载仓库根 inspect.conf，返回通用的参数候选值映射。

    格式：`参数名 = 值1|值2|...`；整行 `#` 注释和空行忽略。未知参数不拒绝，
    以便未来中间件直接扩展 `middleware_parameter`，但参数名必须是安全标识符。
    inspect.conf 缺失时返回空候选集，由具体中间件把无法发现的指标判为 UNKNOWN。
    """
    source = Path(path) if path is not None else _repo_root() / DEFAULT_RUNTIME_CONFIG_NAME
    if not source.is_file():
        return {key: list(values) for key, values in INSPECT_CONF_EMPTY_DEFAULTS.items()}
    _ensure_private_runtime_config(source)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"inspect.conf 无法读取: {source}（{exc}）") from exc

    result: Dict[str, List[str]] = {
        key: list(values) for key, values in INSPECT_CONF_EMPTY_DEFAULTS.items()
    }
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"inspect.conf 第 {lineno} 行缺少 '=': {source}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not _CONF_KEY_RE.fullmatch(key):
            raise ConfigError(f"inspect.conf 第 {lineno} 行参数名非法: {key!r}")
        result[key] = _split_conf_values(value, source=str(source), lineno=lineno)
    return result


def load_inspect_timeout(
    config: Optional[Dict[str, List[str]]] = None,
) -> int:
    """读取并校验 inspect.conf 的全局 timeout（秒）。

    timeout 必须是单个整数，范围 1-60 秒。保留一个较小上限是为了避免
    配置错误把 SSH/命令等待放大到不可控；默认值为 3 秒。
    """
    data = config if config is not None else load_inspect_conf()
    values = data.get("timeout", [str(DEFAULT_INSPECT_TIMEOUT_SEC)])
    if len(values) != 1:
        raise ConfigError("inspect.conf timeout 必须是单个秒数，不能使用 | 分隔多个值")
    raw = str(values[0]).strip()
    if not re.fullmatch(r"[0-9]+", raw):
        raise ConfigError(f"inspect.conf timeout 必须为整数秒: {raw!r}")
    value = int(raw)
    if not MIN_INSPECT_TIMEOUT_SEC <= value <= MAX_INSPECT_TIMEOUT_SEC:
        raise ConfigError(
            "inspect.conf timeout 超出范围: "
            f"{value}（允许 {MIN_INSPECT_TIMEOUT_SEC}-{MAX_INSPECT_TIMEOUT_SEC} 秒）"
        )
    return value


def load_keepalived_baseline(
    path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """加载 Keepalived 文档基线阈值 keepalived-p0-v1.yaml。"""
    if path is None:
        path = KEEPALIVED_BASELINE_FILE
    data = _read_yaml_file(path)
    if not isinstance(data, dict):
        raise ConfigError(f"Keepalived 文档基线顶层应为映射: {path}")
    if data.get("schema") != "threshold-baseline-v1":
        raise ConfigError(
            f"Keepalived 文档基线 schema 不匹配（期望 threshold-baseline-v1）: {path}"
        )
    if data.get("version") != KEEPALIVED_BASELINE_VERSION:
        raise ConfigError(
            f"Keepalived 文档基线 version 不匹配（期望 {KEEPALIVED_BASELINE_VERSION}）: {path}"
        )
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"Keepalived 文档基线 metrics 必须为非空映射: {path}")
    return {
        metric_id: _validate_baseline_metric(
            metric_id, spec, path, version=KEEPALIVED_BASELINE_VERSION
        )
        for metric_id, spec in metrics.items()
    }


def load_elasticsearch_baseline(
    path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """加载 Elasticsearch P0/P1 文档基线阈值。"""
    if path is None:
        path = ELASTICSEARCH_BASELINE_FILE
    data = _read_yaml_file(path)
    if not isinstance(data, dict):
        raise ConfigError(f"Elasticsearch 文档基线顶层应为映射: {path}")
    if data.get("schema") != "threshold-baseline-v1":
        raise ConfigError(
            f"Elasticsearch 文档基线 schema 不匹配（期望 threshold-baseline-v1）: {path}"
        )
    if data.get("version") != ELASTICSEARCH_BASELINE_VERSION:
        raise ConfigError(
            f"Elasticsearch 文档基线 version 不匹配（期望 {ELASTICSEARCH_BASELINE_VERSION}）: {path}"
        )
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ConfigError(f"Elasticsearch 文档基线 metrics 必须为非空映射: {path}")
    return {
        metric_id: _validate_baseline_metric(
            metric_id, spec, path, version=ELASTICSEARCH_BASELINE_VERSION
        )
        for metric_id, spec in metrics.items()
    }


def load_nginx_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """从 inspect.conf 读取 Nginx 候选路径、端口、基线和白名单。

    账号/密码不在这里读取，远程认证继续由 inventory/hosts*.ini 交给 Ansible。
    返回的路径与端口均为候选列表，实际首选项由目标主机进程/配置自动发现逻辑决定。
    """
    data = load_inspect_conf(path)
    return {
        "nginx_bin": list(data.get("nginx_bin", [])),
        "nginx_conf": list(data.get("nginx_conf", [])),
        "nginx_log": list(data.get("nginx_log", [])),
        "nginx_error_log": list(data.get("nginx_error_log", [])),
        "nginx_access_log": list(data.get("nginx_access_log", [])),
        "nginx_port": list(data.get("nginx_port", [])),
        "nginx_version": list(data.get("nginx_version", [])),
        "nginx_baseline": list(data.get("nginx_baseline", [])),
        "whitelist": list(data.get("nginx_whitelist", [])),
    }


def load_keepalived_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """从 inspect.conf 读取 Keepalived 路径、VIP、端口、基线和白名单。"""
    data = load_inspect_conf(path)
    return {
        "keepalived_bin": list(data.get("keepalived_bin", [])),
        "keepalived_conf": list(data.get("keepalived_conf", [])),
        "keepalived_log": list(data.get("keepalived_log", [])),
        "keepalived_vip": list(data.get("keepalived_vip", [])),
        "keepalived_port": list(data.get("keepalived_port", [])),
        "keepalived_version": list(data.get("keepalived_version", [])),
        "keepalived_baseline": list(data.get("keepalived_baseline", [])),
        "whitelist": list(data.get("keepalived_whitelist", [])),
    }


def load_elasticsearch_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """读取 Elasticsearch 路径、API、基线和白名单配置。

    ``elasticsearch_api_user``/``elasticsearch_api_password`` 是 Elasticsearch
    HTTP API 的认证参数，与 Ansible SSH 账号密码完全分离。密码只允许存在于
    目标环境的私有 inspect.conf；远程 API 指标使用 Ansible shell 任务环境注入，
    本地模式使用进程环境注入，规范化事实源、JSON 和报表会统一脱敏。
    ``elasticsearch_cacert`` 是 curl ``--cacert`` 的候选证书路径；
    ``elasticsearch_cert`` 继续用于证书有效期检查，并可作为 CA 路径兜底。
    """
    data = load_inspect_conf(path)
    return {key: list(data.get(key, [])) for key in (
        "elasticsearch_bin", "elasticsearch_conf", "elasticsearch_log",
        "elasticsearch_gc_log", "elasticsearch_data", "elasticsearch_backup",
        "elasticsearch_endpoint", "elasticsearch_http_port",
        "elasticsearch_transport_port", "elasticsearch_version",
        "elasticsearch_expected_nodes", "elasticsearch_seed_hosts",
        "elasticsearch_system_user", "elasticsearch_auth_file",
        "elasticsearch_api_user", "elasticsearch_api_password",
        "elasticsearch_cacert", "elasticsearch_cert",
        "elasticsearch_snapshot_repo",
    )} | {"whitelist": list(data.get("elasticsearch_whitelist", []))}


def load_middleware_config(
    module_id: str, path: Optional[Union[str, Path]] = None
) -> Dict[str, List[str]]:
    """Return all inspect.conf defaults for one additional middleware.

    This keeps the configuration contract extensible without teaching the
    parser a new syntax for each adapter.  Unknown keys remain rejected only
    when their identifier is malformed; values are always returned as the
    existing candidate lists.
    """
    data = load_inspect_conf(path)
    prefix = module_id.lower().replace("/", "_") + "_"
    return {key: list(values) for key, values in data.items() if key.startswith(prefix)}


__all__ = [
    "ConfigError",
    "DOC_BASELINE_VERSION",
    "EXIT_CONFIG_ERROR",
    "LAYER_DOCUMENT_BASELINE",
    "LAYER_EXTERNAL_CONFIG",
    "LAYER_UNRESOLVED",
    "NGINX_BASELINE_VERSION",
    "KEEPALIVED_BASELINE_VERSION",
    "ELASTICSEARCH_BASELINE_VERSION",
    "DEFAULT_RUNTIME_CONFIG_NAME",
    "DEFAULT_INSPECT_TIMEOUT_SEC",
    "MIN_INSPECT_TIMEOUT_SEC",
    "MAX_INSPECT_TIMEOUT_SEC",
    "build_resolved_thresholds",
    "load_document_baseline",
    "load_inspect_conf",
    "load_inspect_timeout",
    "load_inspect_config",
    "load_nginx_baseline",
    "load_keepalived_baseline",
    "load_elasticsearch_baseline",
    "load_nginx_config",
    "load_keepalived_config",
    "load_elasticsearch_config",
    "load_middleware_config",
    "load_override",
    "validate_override_document",
]
