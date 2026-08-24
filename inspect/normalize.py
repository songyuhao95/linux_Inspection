"""inspect/normalize.py — 原始输出 → host-result-v1 metric 对象（T-104）。

职责（docs/specs/host-result-v1.md §3/§4、local-metrics-requirements.md §3/§4、
technical-design.md §5.2/§6，TD §4 normalize 行）：
  - 消费 T-103 ansible_runner 回传的主机级结果（{metric_id, rc, stdout,
    stderr, error|null} 列表 + 主机 execution_status/summary），生成
    host-result-v1 事实源文档（HR §2/§3 字段语义）；
  - 10 个 P0 指标解析器（metrics.py parser 字段按名注册，TD §5.2）：
    解析输入基准 = T-103 交付的 tests/fixtures/raw/ 预录输出；
  - 脱敏（REQ-E-09 / HR §1.4）：IP → `<IP>`、凭据零出现；对全部输出
    派生字符串与最终文档做强制扫描（防御式保证，测试可验证）；
  - 派生标识符（inspection_id）生成时先对原始 host 键做安全字符集映射
    （IP→ip、凭据特征→redacted，T-104F），保证 ID 必匹配 schema pattern
    且对文档级强制扫描幂等；业务字段（evidence/error 消息/日志、
    host.name/ip）仍按 `<IP>`/`<REDACTED>` 脱敏；
  - 四状态判定（HR §4 不可变顺序）：采集失败（error 存在）→ UNKNOWN +
    error（不参与业务判定）；外部配置阈值 → 按外部配置（规则按声明
    顺序首个匹配生效，TD §6.2）；无外部配置 → 文档基线；文档无规则
    或冲突 unresolved → UNKNOWN（threshold.notes 注明 missing/conflict）；
    其余 → 文档基线。禁止发明阈值（MR §3）；
  - 执行/业务状态分离：error 存在 → status=UNKNOWN 且 execution_status
    保持采集层结果（SUCCESS/PARTIAL/ERROR，HR §1.2）；
  - 错误码枚举（HR §3.2）与 host-result-v1.schema.json 一致；error 结构
    {code, message, metric_status:"UNKNOWN"}；
  - validate_host_result：内嵌 JSON Schema 语义子集校验器（jsonschema
    未安装时作为机器校验替代，合同 mitigation：schema 文件为真源，
    无运行时依赖时用内嵌子集校验器）。fact_source 写盘前调用。

模块边界（TD §4）：normalize → config/metrics（单向，允许）；不导入
ansible_runner（其返回值为普通 dict 数据，按鸭子类型消费）；不执行
命令、不连接、不做渲染。错误码常量与 ansible_runner 同名同值——二者
均为 HR §3.2 枚举的转写，schema 文件是机器校验真源，此处仅按值消费。

判定边界数值全部来自 MR §5/§6 已批准阈值（linux-common-p0-v1 文档
基线，与 inspect/data/thresholds/linux-common-p0-v1.yaml 规则文本一致）
与 C1-C13 冲突裁决；本模块不发明阈值。单次采样口径（v1 采集为单次）
下的边界说明见各判定函数 docstring。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from inspect import config as config_mod
from inspect import metrics as metrics_registry
from inspect.replay import normalize_replay_command, validate_replay_command, ReplayCommandError

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# host-result-v1 指标切片（HR §3 示例 / 基线文件 scope 字段）
SCOPE = "local-common-p0-v1"

# 业务状态（HR §2.2）
STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_CRIT = "CRIT"
STATUS_UNKNOWN = "UNKNOWN"
STATUSES = (STATUS_OK, STATUS_WARN, STATUS_CRIT, STATUS_UNKNOWN)

# 执行状态（HR §2.1）
STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_ERROR = "ERROR"

# 阈值层（HR §3 threshold.layer / config.py LAYER_* 同值）
LAYER_DOCUMENT_BASELINE = config_mod.LAYER_DOCUMENT_BASELINE
LAYER_EXTERNAL_CONFIG = config_mod.LAYER_EXTERNAL_CONFIG
LAYER_UNRESOLVED = config_mod.LAYER_UNRESOLVED

# 错误码枚举（HR §3.2 / host-result-v1.schema.json error.code 枚举）
ERROR_CONNECTION_FAILED = "CONNECTION_FAILED"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_PERMISSION_DENIED = "PERMISSION_DENIED"
ERROR_COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
ERROR_PARSE_FAILED = "PARSE_FAILED"
ERROR_DATA_MISSING = "DATA_MISSING"
ERROR_PROBE_FAILED = "PROBE_FAILED"
ERROR_UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
ERROR_CODES = (
    ERROR_CONNECTION_FAILED,
    ERROR_TIMEOUT,
    ERROR_PERMISSION_DENIED,
    ERROR_COMMAND_NOT_FOUND,
    ERROR_PARSE_FAILED,
    ERROR_DATA_MISSING,
    ERROR_PROBE_FAILED,
    ERROR_UNSUPPORTED_PROFILE,
)

# error.metric_status（HR §3.2：技术失败一律 UNKNOWN）
METRIC_ERROR_STATUS = STATUS_UNKNOWN

# meta（HR §2 示例；schema meta 字段为 const 的取 const 值）
DEFAULT_META = {
    "control_endpoint": "Linux/WSL Python3",
    "gather_facts": False,
    "serial": 1,
    "become_scope": "minimal",
    "generator": "inspect.sh",
    "generator_version": "0.1.0-draft",
}

# 文档基线判定的“缺一条目”时使用的 threshold 值（HR §7 示例：error 指标全 null）
_NULL_THRESHOLD = {
    "layer": None,
    "rule_id": None,
    "value": None,
    "source_anchor": None,
    "notes": None,
}

# --------------------------------------------------------------------------
# 脱敏（REQ-E-09：IP→<IP>、凭据零出现；HR §1.4）
# --------------------------------------------------------------------------

# IPv4：严格 0-255 八位组（0.0.0.0:9200 只脱敏地址部分，保留端口）
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)

# IPv6：完整 8 组或含 `::` 的缩写形式（带词边界；时间戳如 10:00:01 不含
# `::` 且不足 8 组，不会被误判）
_IPV6_RE = re.compile(
    r"(?i)(?<![\w:])(?:"
    r"(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
    r"|(?:[0-9a-f]{1,4}:){1,7}:"
    r"|(?:[0-9a-f]{1,4}:){1,6}:[0-9a-f]{1,4}"
    r"|(?:[0-9a-f]{1,4}:){1,5}(?::[0-9a-f]{1,4}){1,2}"
    r"|(?:[0-9a-f]{1,4}:){1,4}(?::[0-9a-f]{1,4}){1,3}"
    r"|(?:[0-9a-f]{1,4}:){1,3}(?::[0-9a-f]{1,4}){1,4}"
    r"|(?:[0-9a-f]{1,4}:){1,2}(?::[0-9a-f]{1,4}){1,5}"
    r"|[0-9a-f]{1,4}:(?::[0-9a-f]{1,4}){1,6}"
    r"|:(?::[0-9a-f]{1,4}){1,7}"
    r"|::"
    r")(?![\w:])"
)

# 凭据键值（key=value / key: value / key value；键名前缀一并吞掉 →
# 键值整体替换，最终文本不含键名也不含值，便于零出现断言）
_CRED_VALUE_RE = re.compile(
    r"(?i)((?:[-\w]*?)(?:password|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|auth[_-]?(?:key|token|secret)|username|"
    r"user|login)\b\s*[:=]\s*)(\S+)"
)

# JVM/属性风格（-Dxxx.password=value / xxx_token=value；整体替换）
_JVM_PROP_RE = re.compile(
    r"(?i)(-\w*(?:password|passwd|pwd|secret|token|key|user|auth)\w*=)(\S+)"
)

# URL userinfo（http://user:pass@host → http://<REDACTED>@host；userinfo
# 排除 `<`，使替换产物不再匹配本模式，脱敏幂等）
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)([^/@<\s]+)@")

# 短选项风格（-p secret / --password secret / -u=admin；整体替换）
_CLI_FLAG_RE = re.compile(
    r"(?i)(?<![^\s])(-p|-P|-u|-U|--password|--passwd|--user|--username)"
    r"(?:\s*=\s*|\s+)(\S+)"
)

# 裸凭据关键字兜底（任何剩余出现 → <REDACTED>，保证“凭据零出现”）
_BARE_CRED_RE = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key)\b"
)

MASKED_IP = "<IP>"
MASKED_CRED = "<REDACTED>"

# 派生标识符安全占位（T-104F）：inspection_id 内不允许 `<IP>`/`<REDACTED>`
# （不在 schema pattern 字符集内），IP/凭据特征映射为可读安全占位
_ID_IP_PLACEHOLDER = "ip"
_ID_CRED_PLACEHOLDER = "redacted"


def mask_ip(text: str) -> str:
    """IP → <IP>（IPv4 严格八位组 + IPv6 完整/:: 缩写形式）。"""
    text = _IPV4_RE.sub(MASKED_IP, text)
    return _IPV6_RE.sub(MASKED_IP, text)


def mask_credentials(text: str) -> str:
    """凭据零出现：键值/属性/URL userinfo/短选项/裸关键字整体 → <REDACTED>。

    键值构造（key=value 等）连同键名整体替换，替换产物不再被任何模式
    匹配（脱敏幂等）；最终文档经 _sweep_strings 扫描后 contains_credential
    为 False（测试可验证）。
    """
    text = _CRED_VALUE_RE.sub(MASKED_CRED, text)
    text = _JVM_PROP_RE.sub(MASKED_CRED, text)
    text = _URL_USERINFO_RE.sub(lambda m: m.group(1) + MASKED_CRED + "@", text)
    text = _CLI_FLAG_RE.sub(MASKED_CRED, text)
    return _BARE_CRED_RE.sub(MASKED_CRED, text)


def mask_output(text: str) -> str:
    """输出派生字符串的统一脱敏入口：先 IP 后凭据（幂等可重复调用）。"""
    return mask_credentials(mask_ip(text))


def contains_plain_ip(text: str) -> bool:
    """测试/断言辅助：文本中是否仍含明文 IP（IPv4 或 IPv6）。"""
    return bool(_IPV4_RE.search(text) or _IPV6_RE.search(text))


def contains_credential(text: str) -> bool:
    """测试/断言辅助：文本中是否仍含凭据特征（键或值）。"""
    return bool(
        _CRED_VALUE_RE.search(text)
        or _JVM_PROP_RE.search(text)
        or _URL_USERINFO_RE.search(text)
        or _CLI_FLAG_RE.search(text)
        or _BARE_CRED_RE.search(text)
    )


def _sweep_strings(obj: Any) -> Any:
    """递归扫描文档全部字符串并强制脱敏（防御式最终保证）。

    即使某个解析器漏脱敏，最终落盘的文档也满足 IP→<IP>、凭据零出现。
    """
    if isinstance(obj, str):
        return mask_output(obj)
    if isinstance(obj, dict):
        return {k: _sweep_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sweep_strings(v) for v in obj]
    return obj


# --------------------------------------------------------------------------
# 解析层
# --------------------------------------------------------------------------


class ParseError(Exception):
    """解析失败（HR §3.2 → error.code=PARSE_FAILED，status=UNKNOWN）。"""


def _content_lines(output: str) -> List[str]:
    """去除首部 `#` 注释行（夹具声明，RK-R2-06）与空行后的内容行。"""
    out = []
    for ln in (output or "").splitlines():
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        out.append(ln.rstrip())
    return out


# -- local.process.present ---------------------------------------------------


def parse_process_present(output: str) -> Dict[str, Any]:
    """pgrep/ps 匹配行 → present/absent + 匹配行数（MR §5.1 / TD §5.2）。

    输入基准（T-103 fixtures/raw/node-a/local.process.present.out）：
      `4321 /usr/bin/java -Xms1g ... org.elasticsearch.bootstrap.Elasticsearch`
    行数 ≥1 → present；0 → absent。摘要取前 3 行并脱敏。
    """
    lines = _content_lines(output)
    return {
        "present": len(lines) > 0,
        "count": len(lines),
        "summary": [mask_output(ln) for ln in lines[:3]],
    }


# -- local.service.active ----------------------------------------------------


def parse_service_active(output: str) -> Dict[str, Any]:
    """systemctl is-active + show 输出 → ActiveState/SubState（MR §5.2）。

    输入基准（fixtures/raw/node-a/local.service.active.out）：
      `active` / `ActiveState=active` / `SubState=running`
    优先取 `ActiveState=` 行；无则回退 is-active 首行。
    """
    active_state: Optional[str] = None
    substate: Optional[str] = None
    is_active: Optional[str] = None
    for ln in _content_lines(output):
        stripped = ln.strip()
        if stripped and is_active is None:
            is_active = stripped
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            k = key.strip().lower()
            if k == "activestate":
                active_state = value.strip()
            elif k == "substate":
                substate = value.strip()
    if active_state is None:
        active_state = is_active
    if active_state is None:
        raise ParseError("systemctl 输出中未找到 ActiveState/is-active 值")
    return {
        "active_state": active_state,
        "substate": substate,
        "is_active": is_active,
    }


# -- local.port.listening ----------------------------------------------------


_SS_LISTEN_RE = re.compile(r"^LISTEN\s+\S+\s+\S+\s+(?P<local>\S+):(?P<port>\d+)\s+")


def parse_port_listening(output: str) -> Dict[str, Any]:
    """ss -tlnp LISTEN 行 → 端口列表 + 监听进程名（MR §5.3 / TD §5.2）。

    输入基准（fixtures/raw/node-a/local.port.listening.out）：
      `LISTEN 0 511 0.0.0.0:9200 0.0.0.0:* users:(("java",pid=4321,fd=130))`
    监听地址脱敏为 <IP>（保留端口），进程名从 users:((("…" 摘取。
    无 LISTEN 行 → ParseError（PARSE_FAILED）。
    """
    ports: List[int] = []
    listeners: List[str] = []
    rows: List[Dict[str, Any]] = []
    for ln in _content_lines(output):
        m = _SS_LISTEN_RE.match(ln)
        if not m:
            continue
        port = int(m.group("port"))
        procs: List[str] = []
        users_pos = ln.find("users:")
        if users_pos != -1:
            procs = re.findall(r'"([^"]+)"', ln[users_pos:])
        if port not in ports:
            ports.append(port)
        for p in procs:
            if p not in listeners:
                listeners.append(p)
        rows.append({"port": port, "line": mask_output(ln)})
    if not ports:
        raise ParseError("ss -tlnp 输出中未找到 LISTEN 行")
    return {"ports": sorted(ports), "listeners": listeners, "rows": rows}


# -- local.cpu.utilization ---------------------------------------------------


_CPU_LINE_RE = re.compile(r"%Cpu\(s\):\s+([\d.]+)\s+us,\s+([\d.]+)\s+sy,")
# ps -eo pid,comm,%cpu,%mem 表头（与 top 进程表头 "PID USER PR NI …" 区分）
_PS_HEADER_RE = re.compile(r"^\s*PID\s+COMMAND\s+%CPU\s+%MEM")


def parse_cpu_utilization(output: str) -> Dict[str, Any]:
    """top -bn2 -d 1 + ps 输出 → 一秒采样窗口内的 us/sy、us+sy 与 Top 进程行数（MR §5.4）。

    输入基准（fixtures/raw/node-a/local.cpu.utilization.out）：
      `%Cpu(s):  2.5 us,  0.8 sy, ...` → us+sy=3.3。
    无 %Cpu(s) 行 → ParseError。
    """
    us = sy = None
    top_rows = 0
    seen_header = False
    for ln in _content_lines(output):
        m = _CPU_LINE_RE.search(ln)
        if m:
            us = float(m.group(1))
            sy = float(m.group(2))
            continue
        if _PS_HEADER_RE.match(ln):
            seen_header = True
            continue
        if seen_header and re.match(r"\s*\d+", ln):
            top_rows += 1
    if us is None or sy is None:
        raise ParseError("top 输出中未找到 %Cpu(s) 行")
    return {"us": us, "sy": sy, "total": round(us + sy, 1), "top_rows": top_rows}


# -- local.cpu.load_1m -------------------------------------------------------


def parse_cpu_load_1m(output: str) -> Dict[str, Any]:
    """/proc/loadavg + nproc → load_1m/5m/15m 与核数（MR §5.5）。

    输入基准（fixtures/raw/node-a/local.cpu.load_1m.out）：
      `0.52 0.44 0.39 1/210 12345` + 第二行核数 `8`。
    核数缺失 → nproc=None（判定层 → UNKNOWN，MR §5.5）。
    """
    lines = _content_lines(output)
    if not lines:
        raise ParseError("loadavg 输出为空")
    parts = lines[0].split()
    if len(parts) < 3:
        raise ParseError(f"loadavg 行格式异常: {lines[0]!r}")
    try:
        load_1m = float(parts[0])
        load_5m = float(parts[1])
        load_15m = float(parts[2])
    except ValueError as exc:
        raise ParseError(f"loadavg 数值解析失败: {lines[0]!r}") from exc
    nproc: Optional[int] = None
    if len(lines) > 1:
        try:
            nproc = int(lines[1].strip())
        except ValueError:
            nproc = None
    return {
        "load_1m": load_1m,
        "load_5m": load_5m,
        "load_15m": load_15m,
        "nproc": nproc,
    }


# -- local.memory.available_percent ------------------------------------------


_MEM_LINE_RE = re.compile(r"^Mem:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")


def parse_memory_available_percent(output: str) -> Dict[str, Any]:
    """free -m Mem 行 → available/total×100 取整（MR §5.6）。

    输入基准（fixtures/raw/node-a/local.memory.available_percent.out）：
      `Mem: 31969 4102 21133 2000 6734 26351` → 26351/31969×100≈82。
    无 Mem 行 → ParseError。
    """
    for ln in _content_lines(output):
        m = _MEM_LINE_RE.match(ln)
        if m:
            total = int(m.group(1))
            available = int(m.group(6))
            if total == 0:
                raise ParseError("free -m Mem 行 total 为 0")
            pct = round(available / total * 100)
            return {"pct": pct, "available": available, "total": total}
    raise ParseError("free -m 输出中未找到 Mem 行")


# -- local.swap.used_percent -------------------------------------------------


_SWAP_LINE_RE = re.compile(r"^Swap:\s+(\d+)\s+(\d+)\s+(\d+)")


def parse_swap_used_percent(output: str) -> Dict[str, Any]:
    """free -m Swap 行 → used/total×100（MR §5.7；total=0 视为未配置）。

    输入基准（fixtures/raw/node-a/local.swap.used_percent.out）：
      `Swap: 8191 0 8191` → used=0 → OK 基线。
    无 Swap 行/空输出 → 未配置（configured=False，判定 =0/未配置 → OK）。
    """
    for ln in _content_lines(output):
        m = _SWAP_LINE_RE.match(ln)
        if m:
            total = int(m.group(1))
            used = int(m.group(2))
            pct = round(used / total * 100) if total > 0 else 0
            return {"pct": pct, "used": used, "total": total, "configured": total > 0}
    return {"pct": 0, "used": 0, "total": 0, "configured": False}


# -- local.filesystem.used_percent -------------------------------------------


_DF_USE_RE = re.compile(r"^(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)%\s+(\S.*)$")


def parse_filesystem_used_percent(output: str) -> Dict[str, Any]:
    """df -hT → 各文件系统 Use% 取最大值（MR §5.8，多目录按文件系统取最大）。

    输入基准（fixtures/raw/node-a/local.filesystem.used_percent.out）：
      `/dev/sda1 ... 66% /` + `/dev/sdb1 ... 91% /data` → max=91。
    无数据行 → ParseError。
    """
    rows: List[Dict[str, Any]] = []
    for ln in _content_lines(output):
        m = _DF_USE_RE.match(ln)
        if m:
            rows.append(
                {
                    "filesystem": m.group(1),
                    "pct": int(m.group(2)),
                    "mount": m.group(3),
                }
            )
    if not rows:
        raise ParseError("df -hT 输出中未找到文件系统行")
    return {"max_pct": max(r["pct"] for r in rows), "rows": rows}


# -- local.filesystem.inode_used_percent -------------------------------------


_DF_INODE_RE = re.compile(r"^(\S+)\s+\S+\s+\S+\s+\S+\s+(\d+)%\s+(\S.*)$")


def parse_filesystem_inode_used_percent(output: str) -> Dict[str, Any]:
    """df -i → 各文件系统 IUse% 取最大值（MR §5.9）。

    输入基准（fixtures/raw/node-a/local.filesystem.inode_used_percent.out）：
      `/dev/sda1 6553600 65536 6488064 1% /` → max=1。
    无数据行 → ParseError。
    """
    rows: List[Dict[str, Any]] = []
    for ln in _content_lines(output):
        m = _DF_INODE_RE.match(ln)
        if m:
            rows.append(
                {
                    "filesystem": m.group(1),
                    "pct": int(m.group(2)),
                    "mount": m.group(3),
                }
            )
    if not rows:
        raise ParseError("df -i 输出中未找到文件系统行")
    return {"max_pct": max(r["pct"] for r in rows), "rows": rows}


# -- local.logs.key_evidence -------------------------------------------------


_SEVERITY_RE = re.compile(r"\[(ERROR|WARN|FATAL|CRITICAL|EXCEPTION)\s*\]", re.IGNORECASE)


def parse_logs_key_evidence(output: str) -> Dict[str, Any]:
    """日志命中行 → 命中数 + 严重度分布 + 最近命中摘要（MR §5.10）。

    输入基准（fixtures/raw/node-a/local.logs.key_evidence.out）：
      3 行（ERROR×2、WARN×1）→ hit_count=3；最近 2 行脱敏后摘要。
    空输出 → hit_count=0（无新增错误 → OK 基线）。
    """
    lines = _content_lines(output)
    counts: Dict[str, int] = {}
    for ln in lines:
        sev = _SEVERITY_RE.search(ln)
        key = sev.group(1).upper() if sev else "OTHER"
        counts[key] = counts.get(key, 0) + 1
    return {
        "hit_count": len(lines),
        "keyword_counts": counts,
        "last_hits": [mask_output(ln) for ln in lines[-2:]],
    }


# -- local.nginx.* -----------------------------------------------------------


def _strip_ls_marker(output: str) -> str:
    """去掉 nginx 命令前置的 `ls -1 <path>` 标记行。

    nginx 采集命令用 `ls -1 <path> 2>/dev/null;` 区分“文件缺失”与“无命中”：
    文件存在时输出首行为路径（标记），随后才是指标内容；文件缺失时输出为空。
    """
    lines = _content_lines(output)
    if not lines:
        return ""
    return "\n".join(lines[1:])


def _has_file_marker(output: str) -> bool:
    """nginx 命令输出是否包含 `ls -1` 文件标记（非空即文件存在）。"""
    return bool(_content_lines(output))


def _has_nginx_missing_marker(output: str, marker: str) -> bool:
    return marker in _content_lines(output)


def parse_nginx_config_valid(output: str) -> Dict[str, Any]:
    """nginx -t 输出 → valid/invalid（syntax is ok + test is successful）。

    输入基准（tests/fixtures/raw/nginx-*/local.nginx.config.valid.out）：
      `nginx: configuration file /opt/nginx/conf/nginx.conf test is successful`
      （首行为 `nginx: the configuration file ... syntax is ok`）。
    """
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_CONFIG_NOT_FOUND"):
        raise ParseError("未发现运行实例的 Nginx 配置文件（进程参数与 inspect.conf 候选均无可用路径）")
    text = output.lower()
    valid = "syntax is ok" in text and "test is successful" in text
    return {
        "valid": valid,
        "summary": [mask_output(ln) for ln in _content_lines(output)[:5]],
    }


_NGINX_VERSION_RE = re.compile(r"\b(nginx/[0-9][A-Za-z0-9._-]*)\b", re.IGNORECASE)


def parse_nginx_version(output: str) -> Dict[str, Any]:
    """从运行中的 Nginx 二进制 ``-v`` 输出提取版本标识。"""
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_RUNNING_NOT_FOUND"):
        raise ParseError("未发现运行中的 Nginx master 或其可执行文件")
    lines = _content_lines(output)
    match = _NGINX_VERSION_RE.search(output)
    if not match:
        raise ParseError("nginx -v 未返回可识别的 nginx/版本号")
    return {
        "version": match.group(1),
        "summary": [mask_output(ln) for ln in lines[:3]],
    }


_NGINX_HTTP_STATUS_RE = re.compile(r"\bHTTP/[0-9.]+[ \t]+(?P<status>[1-5][0-9]{2})")


def parse_nginx_port_listening(output: str) -> Dict[str, Any]:
    """netstat + curl output → 端口监听状态与本地 HTTP 状态。

    ``netstat -lntp`` is the Nginx-specific collector contract.  Keep accepting
    the historical ``ss`` LISTEN row so old replay fixtures remain valid.
    """
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_PORT_NOT_FOUND"):
        raise ParseError("未发现 Nginx 配置中的 listen 端口，且 inspect.conf 没有可用端口候选")
    lines = _content_lines(output)
    listening = any(
        re.search(r"(?:^|\s)LISTEN(?:\s|$)", ln, re.IGNORECASE)
        for ln in lines
    )
    http_status: Optional[int] = None
    for ln in lines:
        m = _NGINX_HTTP_STATUS_RE.search(ln)
        if m:
            http_status = int(m.group("status"))
            break
    return {
        "listening": listening,
        "http_status": http_status,
        "rows": [mask_output(ln) for ln in lines[:6]],
    }


def parse_nginx_error_log(output: str) -> Dict[str, Any]:
    """Nginx error.log 关键错误扫描（P0 关键日志）。

    前置 `ls -1` 标记：输出为空 → 文件缺失/不可读 → ParseError（UNKNOWN）；
    文件存在但无错误命中 → hit_count=0（OK）。
    """
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_ERROR_LOG_NOT_FOUND"):
        raise ParseError("未发现 Nginx error.log（进程参数、配置文件与 inspect.conf 候选均无可用路径）")
    if not _has_file_marker(output):
        raise ParseError("Nginx error.log 不可读（文件缺失/无权限）")
    return parse_logs_key_evidence(_strip_ls_marker(output))


def parse_nginx_connections_status(output: str) -> Dict[str, Any]:
    """curl /nginx_status → stub_status 连接数（未开启 → configured=False）。"""
    active = re.search(r"Active connections:\s*(\d+)", output)
    if not output.strip() or active is None:
        return {
            "configured": False, "active": 0,
            "reading": 0, "writing": 0, "waiting": 0,
        }
    def _num(pat: str) -> int:
        m = re.search(pat, output)
        return int(m.group(1)) if m else 0
    return {
        "configured": True,
        "active": int(active.group(1)),
        "reading": _num(r"Reading:\s*(\d+)"),
        "writing": _num(r"Writing:\s*(\d+)"),
        "waiting": _num(r"Waiting:\s*(\d+)"),
    }


_NGINX_STATUS_CODE_RE = re.compile(r"(?<![0-9])(?P<code>[1-5][0-9]{2})(?![0-9])")


def parse_nginx_access_log_status_codes(output: str) -> Dict[str, Any]:
    """访问日志状态码行 → 5xx 命中数与分布（P1 访问日志状态码）。

    前置 `ls -1` 标记：输出为空 → 文件缺失 → ParseError（UNKNOWN）。
    """
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_ACCESS_LOG_NOT_FOUND"):
        raise ParseError("未发现 Nginx access.log（nginx -T、进程参数与 inspect.conf 候选均无可用路径）")
    if not _has_file_marker(output):
        raise ParseError("Nginx 访问日志不可读（文件缺失/无权限）")
    lines = _content_lines(_strip_ls_marker(output))
    counts: Dict[str, int] = {}
    for ln in lines:
        m = _NGINX_STATUS_CODE_RE.search(ln)
        if not m:
            continue
        code = int(m.group("code"))
        key = f"{code // 100}xx"
        counts[key] = counts.get(key, 0) + 1
    return {
        "five_xx": counts.get("5xx", 0),
        "counts": counts,
        "last_hits": [mask_output(ln) for ln in lines[-5:]],
    }


def parse_nginx_config_baseline(output: str) -> Dict[str, Any]:
    """Nginx 配置基线 grep 输出 → 关键指令命中集合（P1 配置基线）。"""
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_CONFIG_NOT_FOUND"):
        raise ParseError("未发现可读取的 Nginx 配置文件")
    if not _has_file_marker(output):
        raise ParseError("Nginx 配置文件不可读（文件缺失/无权限）")
    directives: List[str] = []
    seen: set = set()
    for ln in _content_lines(_strip_ls_marker(output)):
        key = ln.strip().split(None, 1)[0].split(";", 1)[0].strip()
        if key and key not in seen:
            seen.add(key)
            directives.append(key)
    return {
        "directives": sorted(directives),
        "rows": [mask_output(ln) for ln in _content_lines(_strip_ls_marker(output))[:10]],
    }


def parse_nginx_security_baseline(output: str) -> Dict[str, Any]:
    """Nginx 安全配置基线 grep 输出 → server_tokens/autoindex 状态（P1 安全基线）。"""
    if _has_nginx_missing_marker(output, "INSPECT_NGINX_CONFIG_NOT_FOUND"):
        raise ParseError("未发现可读取的 Nginx 配置文件")
    if not _has_file_marker(output):
        raise ParseError("Nginx 配置文件不可读（文件缺失/无权限）")
    lines = _content_lines(_strip_ls_marker(output))
    lower = "\n".join(lines).lower()
    return {
        "server_tokens_off": bool(re.search(r"server_tokens\s+off", lower)),
        "autoindex_off": bool(re.search(r"autoindex\s+off", lower)),
        "rows": [mask_output(ln) for ln in lines[:10]],
    }


_NGINX_PROXY_UPSTREAM_RE = re.compile(
    r"\bupstream\s+([A-Za-z0-9_.:-]+)\s*\{", re.IGNORECASE
)
_NGINX_PROXY_PASS_RE = re.compile(
    r"\bproxy_pass\s+([^;\s]+)\s*;", re.IGNORECASE
)
_NGINX_PROXY_HEADER_RE = re.compile(
    r"\bproxy_set_header\s+([^;]+?)\s*;", re.IGNORECASE
)


def parse_nginx_http_reachability(output: str) -> Dict[str, Any]:
    """Parse the first HTTP response status emitted by a local Nginx probe."""
    match = _NGINX_HTTP_STATUS_RE.search(output or "")
    if match is None:
        raise ParseError("Nginx HTTP 响应缺少状态码")
    status = int(match.group("status"))
    return {
        "reachable": True,
        "http_status": status,
        "summary": [mask_output(ln) for ln in _content_lines(output)[:3]],
    }


def parse_nginx_stub_status_connections(output: str) -> Dict[str, Any]:
    """Parse the Nginx v2 stub_status fact using the existing parser contract."""
    return parse_nginx_connections_status(output)


def parse_nginx_proxy_upstream_config(output: str) -> Dict[str, Any]:
    """Extract upstream/proxy directives from an ``nginx -T`` evidence stream."""
    text = output or ""
    upstreams = list(dict.fromkeys(_NGINX_PROXY_UPSTREAM_RE.findall(text)))
    proxy_passes = list(dict.fromkeys(_NGINX_PROXY_PASS_RE.findall(text)))
    proxy_set_headers = [
        item.strip() for item in _NGINX_PROXY_HEADER_RE.findall(text) if item.strip()
    ]
    if not upstreams and not proxy_passes and not proxy_set_headers:
        raise ParseError("Nginx upstream/proxy 配置缺少可解析证据")
    return {
        "upstreams": upstreams,
        "proxy_passes": proxy_passes,
        "proxy_set_headers": list(dict.fromkeys(proxy_set_headers)),
        "rows": [mask_output(ln) for ln in _content_lines(text)[:20]],
    }


def parse_nginx_fd_process_limits(output: str) -> Dict[str, Any]:
    """Extract Nginx master nofile and process-limit facts."""
    text = output or ""
    nofile_match = re.search(r"LimitNOFILE\s*=\s*(\d+)", text, re.IGNORECASE)
    if nofile_match is None:
        nofile_match = re.search(r"Max open files\s+(\d+)", text, re.IGNORECASE)
    process_match = re.search(r"Max processes\s+(\d+)", text, re.IGNORECASE)
    if nofile_match is None or process_match is None:
        raise ParseError("Nginx 文件描述符或进程限制缺少可解析证据")
    return {
        "nofile": int(nofile_match.group(1)),
        "max_processes": int(process_match.group(1)),
        "rows": [mask_output(ln) for ln in _content_lines(text)[:10]],
    }


def parse_nginx_https_certificate(output: str) -> Dict[str, Any]:
    """Extract certificate paths and OpenSSL ``notAfter`` evidence."""
    text = output or ""
    certificates = list(
        dict.fromkeys(
            re.findall(r"\bssl_certificate\s+([^;\s]+)\s*;", text, re.IGNORECASE)
        )
    )
    not_after = list(
        dict.fromkeys(
            m.group(1).strip()
            for m in re.finditer(
                r"\bnotAfter\s*=\s*(.+?)\s*$",
                text,
                re.IGNORECASE | re.MULTILINE,
            )
        )
    )
    if not certificates and not not_after:
        raise ParseError("Nginx HTTPS 证书缺少证书路径或 notAfter 证据")
    return {
        "certificates": certificates,
        "not_after": not_after,
        "rows": [mask_output(ln) for ln in _content_lines(text)[:10]],
    }


# -- local.keepalived.* ------------------------------------------------------


def _has_keepalived_missing_marker(output: str, marker: str) -> bool:
    return marker in _content_lines(output)


_KEEPALIVED_VERSION_RE = re.compile(
    r"\bkeepalived\s*(?:v|/)?\s*([0-9][A-Za-z0-9._-]*)\b", re.IGNORECASE
)


def parse_keepalived_version(output: str) -> Dict[str, Any]:
    """从运行中的 Keepalived ``-v`` 输出提取统一的 keepalived/x.y.z。"""
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_RUNNING_NOT_FOUND"):
        raise ParseError("未发现运行中的 Keepalived 或其可执行文件")
    match = _KEEPALIVED_VERSION_RE.search(output)
    if not match:
        raise ParseError("keepalived -v 未返回可识别版本号")
    version = "keepalived/" + match.group(1)
    return {"version": version, "summary": [mask_output(ln) for ln in _content_lines(output)[:3]]}


_IP_WITH_PREFIX_RE = re.compile(r"(?<![0-9A-Fa-f:.])([0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{0,4}){2,7}|[0-9]{1,3}(?:\.[0-9]{1,3}){3})(?:/[0-9]+)?")


def _without_prefix(value: str) -> str:
    return value.split("/", 1)[0].strip()


def parse_keepalived_vip_bound(output: str) -> Dict[str, Any]:
    """解析配置角色/VIP 与 ``ip -brief addr`` 的实际绑定结果。"""
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_CONFIG_NOT_FOUND"):
        raise ParseError("未发现 Keepalived 配置文件（进程参数与 inspect.conf 候选均无可用路径）")
    lines = _content_lines(output)
    state = ""
    expected: List[str] = []
    for line in lines:
        if line.startswith("CONFIG_STATE="):
            state = line.split("=", 1)[1].strip().upper()
        elif line.startswith("CONFIG_VIP="):
            value = _without_prefix(line.split("=", 1)[1])
            if value:
                expected.append(value)
    if not state or not expected:
        raise ParseError("Keepalived 配置缺少 state 或 virtual_ipaddress")
    actual_text = "\n".join(
        line for line in lines
        if not line.startswith(("INSPECT_", "CONFIG_"))
    )
    actual = {_without_prefix(m.group(0)) for m in _IP_WITH_PREFIX_RE.finditer(actual_text)}
    bound = [vip for vip in expected if vip in actual]
    return {
        "state": state,
        "expected_vips": expected,
        "bound_vips": bound,
        "bound": bool(bound),
        "summary": [mask_output(line) for line in lines[-8:]],
    }


_HTTP_STATUS_RE = re.compile(r"\bHTTP/[0-9.]+[ \t]+(?P<status>[1-5][0-9]{2})")


def parse_keepalived_vip_access(output: str) -> Dict[str, Any]:
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_VIP_NOT_FOUND"):
        raise ParseError("未发现 Keepalived VIP 或访问端口")
    lines = _content_lines(output)
    accesses = [line for line in lines if line.startswith("CONFIG_ACCESS=")]
    statuses = [int(m.group("status")) for m in (_HTTP_STATUS_RE.search(line) for line in lines) if m]
    if not accesses:
        raise ParseError("未生成 Keepalived VIP 访问目标")
    return {
        "targets": [line.split("=", 1)[1] for line in accesses],
        "http_status": statuses[0] if statuses else None,
        "reachable": bool(statuses),
        "rows": [mask_output(line) for line in lines[-8:]],
    }


def _keepalived_content_lines(output: str) -> List[str]:
    return [
        line for line in _content_lines(output)
        if not line.startswith("INSPECT_KEEPALIVED_")
        and not line.startswith("CONFIG_")
    ]


def parse_keepalived_config_baseline(output: str) -> Dict[str, Any]:
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_CONFIG_NOT_FOUND"):
        raise ParseError("未发现可读取的 Keepalived 配置文件")
    lines = _keepalived_content_lines(output)
    directives = set()
    for line in lines:
        for name in (
            "state", "interface", "virtual_router_id", "priority", "advert_int",
            "virtual_ipaddress", "script", "track_script",
        ):
            if re.search(r"\b" + re.escape(name) + r"\b", line):
                directives.add(name)
    if not lines:
        raise ParseError("Keepalived 配置文件不可读或无关键配置输出")
    return {"directives": sorted(directives), "rows": [mask_output(line) for line in lines[:15]]}


def parse_keepalived_healthcheck(output: str) -> Dict[str, Any]:
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_CONFIG_NOT_FOUND"):
        raise ParseError("未发现 Keepalived 配置文件")
    lines = _content_lines(output)
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_SCRIPT_NOT_FOUND"):
        return {"configured": False, "script": None, "present": False, "executable": False, "rows": []}
    script = next((line.split("=", 1)[1] for line in lines if line.startswith("CONFIG_SCRIPT=")), None)
    if not script:
        raise ParseError("未发现 Keepalived 健康检查脚本引用")
    executable = any(line == "SCRIPT_EXECUTABLE=true" for line in lines)
    return {
        "configured": True,
        "script": mask_output(script),
        "present": executable,
        "executable": executable,
        "rows": [mask_output(line) for line in lines[-5:]],
    }


def parse_keepalived_error_log(output: str) -> Dict[str, Any]:
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_LOG_NOT_FOUND"):
        raise ParseError("未发现 Keepalived 日志文件（进程/inspect.conf 候选均无可用路径）")
    lines = [
        line for line in _content_lines(output)
        if not line.startswith("INSPECT_KEEPALIVED_LOG=")
    ]
    text = "\n".join(lines)
    transitions = len(re.findall(r"Entering (?:MASTER|BACKUP)", text, re.IGNORECASE))
    faults = len(re.findall(r"Entering FAULT", text, re.IGNORECASE))
    script_failures = len(re.findall(r"script.*failed", text, re.IGNORECASE))
    return {
        "hit_count": len(lines),
        "transition_count": transitions,
        "fault_count": faults,
        "script_failure_count": script_failures,
        "keyword_counts": {
            "MASTER_BACKUP": transitions,
            "FAULT": faults,
            "SCRIPT_FAILED": script_failures,
        },
        "last_hits": [mask_output(line) for line in lines[-5:]],
    }


def parse_keepalived_capability_stability(output: str) -> Dict[str, Any]:
    if _has_keepalived_missing_marker(output, "INSPECT_KEEPALIVED_CAPABILITY_NOT_FOUND"):
        raise ParseError("未发现 Keepalived 二进制或日志路径")
    lines = _content_lines(output)
    log_marker = next((line for line in lines if line.startswith("INSPECT_KEEPALIVED_LOG=")), None)
    text = "\n".join(lines)
    has_net_admin = bool(re.search(r"cap_net_admin", text, re.IGNORECASE))
    has_net_raw = bool(re.search(r"cap_net_raw", text, re.IGNORECASE))
    log_lines = [line for line in lines if not line.startswith("INSPECT_KEEPALIVED_LOG=")]
    log_text = "\n".join(log_lines)
    transitions = len(re.findall(r"Entering (?:MASTER|BACKUP)", log_text, re.IGNORECASE))
    faults = len(re.findall(r"Entering FAULT", log_text, re.IGNORECASE))
    script_failures = len(re.findall(r"script.*failed", log_text, re.IGNORECASE))
    return {
        "has_net_admin": has_net_admin,
        "has_net_raw": has_net_raw,
        "log_available": log_marker is not None,
        "transition_count": transitions,
        "fault_count": faults,
        "script_failure_count": script_failures,
        "rows": [mask_output(line) for line in lines[-10:]],
    }


# -- local.elasticsearch.* --------------------------------------------------


def _es_lines(output: str) -> List[str]:
    return [
        line for line in _content_lines(output)
        if not line.startswith("INSPECT_ELASTICSEARCH_")
    ]


def _es_http_status(output: str) -> Optional[int]:
    match = re.search(r"INSPECT_ELASTICSEARCH_HTTP_STATUS=(\d{3})", output or "")
    return int(match.group(1)) if match else None


def _es_http_statuses(output: str) -> List[int]:
    return [int(value) for value in re.findall(
        r"INSPECT_ELASTICSEARCH_HTTP_STATUS=(\d{3})", output or ""
    )]


def _reject_es_transport_diagnostics(output: str) -> None:
    """Do not turn curl diagnostics into valid CAT rows or business values."""
    for line in _content_lines(output):
        if re.match(
            r"(?:curl:|Failed to connect|Could not resolve host|URL rejected|"
            r"Connection refused|Empty reply from server)",
            line.strip(),
            re.IGNORECASE,
        ):
            raise ParseError("Elasticsearch API/连接命令未返回可解析数据")


def _es_json(output: str) -> Any:
    _reject_es_transport_diagnostics(output)
    status = _es_http_status(output)
    if status is None:
        raise ParseError("Elasticsearch API 缺少 HTTP 状态标记")
    if status is not None and status >= 400:
        raise ParseError(f"Elasticsearch API HTTP {status}（认证/权限或服务错误）")
    text = "\n".join(_es_lines(output)).strip()
    if not text:
        raise ParseError("Elasticsearch API 未返回内容")
    start = min((idx for idx in (text.find("{"), text.find("[")) if idx >= 0), default=-1)
    if start < 0:
        raise ParseError("Elasticsearch API 返回不是 JSON")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError as exc:
        raise ParseError("Elasticsearch API JSON 解析失败") from exc


def parse_elasticsearch_version(output: str) -> Dict[str, Any]:
    if "INSPECT_ELASTICSEARCH_RUNNING_NOT_FOUND" in _content_lines(output):
        raise ParseError("未发现运行中的 Elasticsearch 或其 API 端点")
    status = _es_http_status(output)
    if status is not None:
        # A real API response always carries the status marker.  Once it is
        # present, an HTTP error or malformed JSON must remain UNKNOWN; never
        # fall through to a version-looking string in an error message.
        data = _es_json(output)
    else:
        # Keep the explicit ``Version:`` fixture compatibility path, but reject
        # transport diagnostics and do not accept arbitrary semver text as a
        # successful API response with a missing status marker.
        _reject_es_transport_diagnostics(output)
        data = None
    if isinstance(data, dict):
        version = data.get("version")
        if isinstance(version, dict) and version.get("number"):
            actual = str(version["number"])
            return {
                "version": actual,
                "summary": [mask_output(x) for x in _content_lines(output)[:3]],
            }
    match = re.search(r"(?:Version|version)\s*[:=]\s*([0-9][A-Za-z0-9._+-]*)", output or "")
    if not match:
        if status is not None:
            raise ParseError("Elasticsearch 根 API 未返回可识别 version.number")
        raise ParseError("Elasticsearch 版本输出缺少明确 Version 字段")
    return {"version": match.group(1), "summary": [mask_output(x) for x in _content_lines(output)[:3]]}


def parse_elasticsearch_cluster_health(output: str) -> Dict[str, Any]:
    data = _es_json(output)
    try:
        return {
            "status": str(data["status"]).lower(),
            "nodes": int(data.get("number_of_nodes", 0)),
            "active_shards_percent": float(data.get("active_shards_percent_as_number", 0)),
            "summary": f"status={data.get('status')}; nodes={data.get('number_of_nodes')}; active_shards_percent={data.get('active_shards_percent_as_number')}",
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError("集群健康 JSON 缺少 status/节点数/分片百分比") from exc


def _es_cat_rows(output: str, *, allow_empty: bool = False) -> List[List[str]]:
    _reject_es_transport_diagnostics(output)
    status = _es_http_status(output)
    if status is None:
        raise ParseError("Elasticsearch CAT API 缺少 HTTP 状态标记")
    if status is not None and status >= 400:
        raise ParseError(f"Elasticsearch API HTTP {status}")
    lines = _es_lines(output)
    if not lines:
        raise ParseError("Elasticsearch CAT API 无返回行")
    rows = []
    header_seen = False
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower() in {"name", "node_name", "index", "shard", "health", "node"}:
            if "health" in {item.lower() for item in parts} and "index" in {
                item.lower() for item in parts
            }:
                header_seen = True
            continue
        rows.append(parts)
    if not rows:
        if allow_empty and header_seen:
            return []
        raise ParseError("Elasticsearch CAT API 无数据行")
    return rows


def parse_elasticsearch_nodes(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    return {"count": len(rows), "rows": rows, "summary": [mask_output(" ".join(row)) for row in rows[:10]]}


def parse_elasticsearch_nodes_cpu(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    values = []
    for row in rows:
        for token in row[2:]:
            if re.fullmatch(r"\d+(?:\.\d+)?", token):
                values.append(float(token))
                break
    if not values:
        raise ParseError("节点 CPU 字段不可解析")
    return {"max_cpu": max(values), "avg_cpu": sum(values) / len(values), "count": len(values), "rows": rows}


def parse_elasticsearch_nodes_memory(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    heaps: List[float] = []
    rams: List[float] = []
    for row in rows:
        nums = [float(token) for token in row[1:] if re.fullmatch(r"\d+(?:\.\d+)?", token)]
        if len(nums) >= 2:
            heaps.append(nums[0]); rams.append(nums[1])
    if not heaps:
        raise ParseError("节点 heap.percent/ram.percent 不可解析")
    return {"max_heap": max(heaps), "max_ram": max(rams) if rams else 0, "count": len(heaps), "rows": rows}


def parse_elasticsearch_nodes_disk(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    values: List[float] = []
    for row in rows:
        for token in reversed(row):
            token = token.rstrip("%")
            if re.fullmatch(r"\d+(?:\.\d+)?", token):
                values.append(float(token)); break
    if not values:
        raise ParseError("allocation disk.percent 不可解析")
    return {"max_disk": max(values), "count": len(values), "rows": rows}


def parse_elasticsearch_watermark(output: str) -> Dict[str, Any]:
    data = _es_json(output)
    text = json.dumps(data, ensure_ascii=False).lower()
    values = {key: (re.search(rf"{key}[^0-9]*(\d+%|\d+gb|\d+g)", text).group(1) if re.search(rf"{key}[^0-9]*(\d+%|\d+gb|\d+g)", text) else None) for key in ("low", "high", "flood_stage")}
    return {"watermarks": values, "current_max_disk": None, "summary": json.dumps(data, ensure_ascii=False)[:600]}


def parse_elasticsearch_shards(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    unassigned_primary = unassigned_replica = initializing = 0
    for row in rows:
        state = next((item.upper() for item in row if item.upper() in {"UNASSIGNED", "INITIALIZING", "STARTED", "RELOCATING"}), "")
        if state == "UNASSIGNED":
            if "p" in row[:4]: unassigned_primary += 1
            else: unassigned_replica += 1
        elif state == "INITIALIZING":
            initializing += 1
    return {"unassigned_primary": unassigned_primary, "unassigned_replica": unassigned_replica, "initializing": initializing, "rows": rows}


def parse_elasticsearch_service_port(output: str) -> Dict[str, Any]:
    lines = _content_lines(output)
    process_marker = re.search(
        r"^INSPECT_ELASTICSEARCH_PROCESS=(true|false)$", output or "", re.MULTILINE
    )
    process = (
        process_marker.group(1) == "true"
        if process_marker
        else any(
            "elasticsearch" in line.lower()
            for line in lines
            if not line.strip().startswith("LISTEN")
        )
    )
    listen_lines = [line for line in lines if line.strip().startswith("LISTEN")]
    ports = sorted({int(x) for x in re.findall(r":(\d+)(?=\s|$)", "\n".join(listen_lines)) if int(x) > 0})
    expected_match = re.search(
        r"^INSPECT_ELASTICSEARCH_EXPECTED_PORTS=([0-9]+),([0-9]+)\r?$",
        output or "",
        re.MULTILINE,
    )
    expected_ports = (
        sorted({int(expected_match.group(1)), int(expected_match.group(2))})
        if expected_match
        else []
    )
    return {
        "process": process,
        "ports": ports,
        "expected_ports": expected_ports,
        "summary": [mask_output(x) for x in lines[:10]],
    }


def parse_elasticsearch_heap_gc(output: str) -> Dict[str, Any]:
    statuses = _es_http_statuses(output)
    if any(status >= 400 for status in statuses):
        raise ParseError(
            "Elasticsearch heap API HTTP "
            + ",".join(str(status) for status in statuses if status >= 400)
        )
    lines = _es_lines(output)
    heaps = [float(x) for x in re.findall(r"(?:^|\s)(\d+(?:\.\d+)?)\s*$", "\n".join(lines))]
    max_heap = max(heaps) if heaps else None
    full_gc = len(re.findall(r"Full", output or "", re.IGNORECASE))
    oom = len(re.findall(r"OutOfMemory", output or "", re.IGNORECASE))
    if max_heap is None and "INSPECT_ELASTICSEARCH_GC_LOG_NOT_FOUND" in _content_lines(output):
        raise ParseError("无法读取 Elasticsearch heap 或 GC 日志")
    return {"max_heap": max_heap, "full_gc": full_gc, "oom": oom, "rows": [mask_output(x) for x in lines[-10:]]}


def parse_elasticsearch_thread_pool(output: str) -> Dict[str, Any]:
    rows = _es_cat_rows(output)
    queue = rejected = 0
    for row in rows:
        nums = [int(x) for x in row if re.fullmatch(r"\d+", x)]
        if len(nums) >= 3:
            queue += nums[-3]; rejected += nums[-2]
    return {"queue": queue, "rejected": rejected, "rows": rows}


def parse_elasticsearch_cluster_settings(output: str) -> Dict[str, Any]:
    data = _es_json(output)
    text = json.dumps(data, ensure_ascii=False).lower()
    restricted = bool(re.search(r"allocation\.enable[^,}]*\b(?:none|primaries)\b|rebalance[^,}]*\bnone\b", text))
    return {"restricted": restricted, "summary": json.dumps(data, ensure_ascii=False)[:600]}


def parse_elasticsearch_discovery_config(output: str) -> Dict[str, Any]:
    lines = _es_lines(output)
    if "INSPECT_ELASTICSEARCH_CONFIG_NOT_FOUND" in _content_lines(output) or not lines:
        raise ParseError("未发现 Elasticsearch 配置文件")
    seed = [line for line in lines if "discovery.seed_hosts" in line]
    initial = [line for line in lines if "cluster.initial_master_nodes" in line]
    return {"seed_hosts": seed, "initial_master_nodes": initial, "rows": [mask_output(x) for x in lines]}


def parse_elasticsearch_indices(output: str) -> Dict[str, Any]:
    # CAT indices with `v` returns only its header when the cluster contains
    # no indices. That is a valid zero-index result, not a parser failure.
    rows = _es_cat_rows(output, allow_empty=True)
    red = sum(1 for row in rows if row[0].lower() == "red")
    yellow = sum(1 for row in rows if row[0].lower() == "yellow")
    return {"count": len(rows), "red": red, "yellow": yellow, "rows": rows}


def parse_elasticsearch_slowlog(output: str) -> Dict[str, Any]:
    lines = _es_lines(output)
    if "INSPECT_ELASTICSEARCH_LOG_NOT_FOUND" in _content_lines(output):
        raise ParseError("未发现 Elasticsearch 日志目录")
    if "INSPECT_ELASTICSEARCH_SLOWLOG_NOT_CONFIGURED" in _content_lines(output):
        return {"files": 0, "hit_count": 0, "rows": []}
    files = [line for line in lines if "slowlog" in line]
    hits = [line for line in lines if line not in files]
    return {"files": len(files), "hit_count": len(hits), "rows": [mask_output(x) for x in hits[-10:]]}


def parse_elasticsearch_security(output: str) -> Dict[str, Any]:
    _reject_es_transport_diagnostics(output)
    statuses = _es_http_statuses(output)
    if not statuses:
        raise ParseError("Elasticsearch security API 缺少 HTTP 状态标记")
    if any(status >= 400 for status in statuses):
        raise ParseError(
            "Elasticsearch security API HTTP "
            + ",".join(str(status) for status in statuses if status >= 400)
        )
    objects = re.findall(r"\{(?:[^{}]|\{[^{}]*\})*\}", "\n".join(_es_lines(output)), re.S)
    if not objects:
        raise ParseError("安全 API 未返回 JSON")
    text = "\n".join(objects).lower()
    superusers = len(re.findall(r"superuser", text))
    users = max(0, len(objects) - 1)
    return {"users": users, "superusers": superusers, "rows": [mask_output(x) for x in objects[:6]]}


def parse_elasticsearch_certificate(output: str) -> Dict[str, Any]:
    if "INSPECT_ELASTICSEARCH_CERT_NOT_FOUND" in _content_lines(output):
        raise ParseError("未发现 Elasticsearch HTTPS 证书")
    match = re.search(r"notAfter=(.+)", output or "", re.IGNORECASE)
    if not match:
        raise ParseError("openssl 未返回 notAfter")
    from email.utils import parsedate_to_datetime
    try:
        expiry = parsedate_to_datetime(match.group(1).strip())
        days = (expiry - datetime.now(expiry.tzinfo)).total_seconds() / 86400
    except (TypeError, ValueError, OverflowError) as exc:
        raise ParseError("证书到期时间不可解析") from exc
    return {"days_remaining": days, "expiry": mask_output(match.group(1).strip())}


def parse_elasticsearch_snapshot(output: str) -> Dict[str, Any]:
    if "INSPECT_ELASTICSEARCH_SNAPSHOT_NOT_FOUND" in _content_lines(output):
        raise ParseError("未配置 Elasticsearch 快照仓库")
    statuses = _es_http_statuses(output)
    _reject_es_transport_diagnostics(output)
    if not statuses:
        raise ParseError("Elasticsearch snapshot API 缺少 HTTP 状态标记")
    if any(status >= 400 for status in statuses):
        # A configured repository name may simply not exist on the target.
        # Elasticsearch reports that business condition as a JSON 404/400;
        # preserve it for the judge as WARN instead of misclassifying it as
        # an authentication/transport parse failure.
        if re.search(r"repository_missing_exception|repository.*missing", output or "", re.IGNORECASE) or (
            any(status in {400, 404} for status in statuses)
            and not any(status in {401, 403} for status in statuses)
        ):
            return {
                "repository_count": 0,
                "verify_ok": False,
                "repository_missing": True,
                "rows": [mask_output(x) for x in _es_lines(output)[-10:]],
            }
        raise ParseError(
            "Elasticsearch snapshot API HTTP "
            + ",".join(str(status) for status in statuses if status >= 400)
        )
    data = _es_lines(output)
    text = "\n".join(data)
    repository_count = len(re.findall(r'"[^"\\]+"\s*:\s*\{\s*"type"\s*:', text))
    verify_ok = (
        any('"nodes"' in line or '"status"' in line for line in data[-10:])
        and not any('"error"' in line for line in data[-10:])
    )
    return {
        "repository_count": repository_count,
        "verify_ok": verify_ok,
        "rows": [mask_output(x) for x in data[-10:]],
    }


def parse_elasticsearch_system_parameters(output: str) -> Dict[str, Any]:
    lines = _content_lines(output)
    max_map = next((int(m.group(1)) for m in [re.search(r"ES_MAX_MAP_COUNT=(\d+)", output or "")] if m), None)
    nofile = next((int(m.group(1)) for m in [re.search(r"ES_ULIMIT_NOFILE=(\d+)", output or "")] if m), None)
    nproc = next((int(m.group(1)) for m in [re.search(r"ES_ULIMIT_NPROC=(\d+)", output or "")] if m), None)
    memlock = re.search(r"ES_ULIMIT_MEMLOCK=([^\s]+)", output or "")
    swap = re.search(r"^Swap:\s+(\d+)\s+(\d+)\s+(\d+)", output or "", re.M)
    if max_map is None or nofile is None or nproc is None or not memlock:
        raise ParseError("系统参数输出不完整")
    swap_used = int(swap.group(2)) if swap else None
    return {"max_map_count": max_map, "nofile": nofile, "nproc": nproc, "memlock": memlock.group(1), "swap_used": swap_used, "rows": [mask_output(x) for x in lines]}


def parse_middleware_text(output: str) -> Dict[str, Any]:
    """Parse a document command whose result is intentionally text-shaped.

    Middleware commands differ widely (CLI tables, JSON, status lines and
    logs).  The raw command output remains the fact; this parser only records
    a bounded, masked sample and an observation count.  The judge below uses
    explicit health/error words when the manual command emits them and never
    treats missing output as healthy.
    """
    lines = _content_lines(output)
    if not lines:
        raise ParseError("中间件命令无输出")
    text = "\n".join(lines[-80:])
    lowered = text.lower()
    return {
        "text": mask_output(text),
        "line_count": len(lines),
        "has_critical_marker": bool(re.search(
            r"(?:fatal|outofmemory|oom|connection refused|not\s+found|inactive|"
            r"unavailable|unassigned|no leader|failed|failure|error|critical|\bdown\b)",
            lowered,
        )),
        "has_warning_marker": bool(re.search(
            r"(?:warn|warning|under[-_ ]replicated|under[-_ ]min|lag|yellow|"
            r"pending|partition|timeout|degraded|\bslow\b)", lowered,
        )),
        "rows": [mask_output(line) for line in lines[-20:]],
    }


# The seven newly-added middleware families use typed facts.  These parsers
# intentionally return only a value and a bounded semantic summary; command
# output is never retained as raw_value/normalized_value.
_TYPED_MIDDLEWARE_PREFIXES = (
    "local.kafka.", "local.mysql.", "local.nacos.", "local.rabbitmq.",
    "local.redis.", "local.rocketmq.", "local.tomcat.",
)
_TYPED_KEEPALIVED_METRIC_IDS = frozenset(
    {
        "local.keepalived.vip.present",
        "local.keepalived.vrrp.role",
        "local.keepalived.health_check.status",
        "local.keepalived.failover.config",
    }
)


def _is_typed_middleware_metric(metric_id: str) -> bool:
    return metric_id.startswith(_TYPED_MIDDLEWARE_PREFIXES) or metric_id in _TYPED_KEEPALIVED_METRIC_IDS


def _typed_middleware_lines(output: str) -> List[str]:
    lines = _content_lines(output)
    if not lines:
        raise ParseError("中间件命令无输出")
    if any(line.startswith("INSPECT_MIDDLEWARE_NOT_RUNNING=") for line in lines):
        raise ParseError("中间件服务进程未运行")
    return lines


def _typed_bool(output: str, positive: str, *, negative: str = "") -> Dict[str, Any]:
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    if negative and re.search(negative, text, re.IGNORECASE):
        value = False
    elif re.search(positive, text, re.IGNORECASE):
        value = True
    else:
        raise ParseError("中间件健康事实缺少可判定标记")
    return {"value": value, "summary": f"typed_health={str(value).lower()}"}


def _typed_number(output: str, pattern: str, *, cast=float, summary: str) -> Dict[str, Any]:
    lines = _typed_middleware_lines(output)
    match = re.search(pattern, "\n".join(lines), re.IGNORECASE | re.MULTILINE)
    if not match:
        raise ParseError("中间件数值事实缺失")
    try:
        value = cast(match.group(1))
    except (TypeError, ValueError):
        raise ParseError("中间件数值事实非法") from None
    return {"value": value, "summary": summary.format(value=value)}


def _typed_count(output: str, pattern: str, *, summary: str) -> Dict[str, Any]:
    lines = _typed_middleware_lines(output)
    matched_lines = [line for line in lines if re.search(pattern, line, re.IGNORECASE)]
    if not matched_lines:
        raise ParseError("中间件计数事实缺失或格式非法")
    count = len(matched_lines)
    return {"value": count, "summary": summary.format(value=count)}


def parse_kafka_zookeeper_health(output):
    return _typed_bool(output, r"\bimok\b|\bleader\b|\bfollower\b|\bzkServer\b", negative=r"connection refused|no leader|failed|error")


def parse_kafka_broker_health(output):
    return _typed_bool(output, r"kafka\.Kafka|\bLISTEN\b|started", negative=r"connection refused|not found|failed|error")


def parse_kafka_controller_health(output):
    return _typed_bool(output, r"controller|brokerid|controllerid", negative=r"no controller|null|failed|error")


def parse_kafka_under_replicated_partitions(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    if not re.search(r"\bTopic\b.*\bPartition\b|^\s*Topic:", text, re.IGNORECASE | re.MULTILINE):
        raise ParseError("Kafka 未充分复制分区输出格式非法")
    value = sum(1 for line in lines if re.search(r"^\s*Topic:", line, re.IGNORECASE))
    return {"value": value, "summary": f"under_replicated_partitions={value}"}


def parse_kafka_under_min_isr(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    if re.search(r"no (?:under[-_ ]min|unavailable)|none|empty", text, re.IGNORECASE):
        value = 0
    elif not re.search(r"\bunder[-_ ]min\b|\bunavailable\b|\bTopic\b.*\bPartition\b|^\s*Topic:", text, re.IGNORECASE | re.MULTILINE):
        raise ParseError("Kafka ISR 输出格式非法")
    else:
        value = sum(1 for line in lines if re.search(r"^\s*Topic:|under[-_ ]min|unavailable", line, re.IGNORECASE))
    return {"value": value, "summary": f"under_min_isr={value}"}


def parse_kafka_zookeeper_latency(output):
    return _typed_number(output, r"zk_max_latency\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)", cast=float, summary="zk_max_latency={value}ms")


def parse_mysql_service_health(output):
    return _typed_bool(output, r"mysqld|\bLISTEN\b|active", negative=r"connection refused|inactive|not found|failed|error")


def parse_mysql_login_version(output):
    return _typed_bool(output, r"\b\d+\.\d+(?:\.\d+)?\b.*\b(?:3306|localhost|127\.0\.0\.1)\b|@@version", negative=r"access denied|error|failed")


def parse_mysql_role_gtid(output):
    return _typed_bool(output, r"server_id.*(?:ON|1)|gtid_mode.*ON.*enforce_gtid_consistency.*ON", negative=r"OFF|error|failed")


def parse_mysql_replica_threads(output):
    return _typed_bool(output, r"Replica_IO_Running\s*:\s*Yes.*Replica_SQL_Running\s*:\s*Yes|Replica_SQL_Running\s*:\s*Yes.*Replica_IO_Running\s*:\s*Yes", negative=r"Replica_(?:IO|SQL)_Running\s*:\s*No|Last_(?:IO|SQL)_Errno\s*:\s*[1-9]")


def parse_mysql_replication_lag(output):
    return _typed_number(output, r"Seconds_Behind_Source\s*:\s*(\d+)", cast=int, summary="replication_lag={value}s")


def parse_mysql_connection_pressure(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    used = re.search(r"Max_used_connections\s+([0-9]+)", text, re.IGNORECASE)
    limit = re.search(r"max_connections\s+([0-9]+)", text, re.IGNORECASE)
    if not used or not limit or int(limit.group(1)) <= 0:
        raise ParseError("MySQL 连接压力数值缺失")
    value = round(int(used.group(1)) * 100.0 / int(limit.group(1)), 2)
    return {"value": value, "summary": f"connection_pressure={value}%"}


def parse_nacos_service_health(output):
    return _typed_bool(output, r"com\.alibaba\.nacos|nacos\.home|startup|active", negative=r"inactive|failed|error|not found")


def parse_nacos_core_ports_health(output):
    return _typed_count(output, r":(?:8848|9848|9849|7848)\b.*LISTEN", summary="nacos_listening_ports={value}")


def parse_nacos_http_health(output):
    return _typed_bool(output, r"\bUP\b|HTTP/1\.[01]\s+200|\"status\"\s*:\s*\"UP\"", negative=r"HTTP/1\.[01]\s+5|connection refused|timeout|failed")


def parse_nacos_cluster_nodes(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    if not re.search(r"\"?alive\"?\s*[:=]\s*(?:true|false|1|0)", text, re.IGNORECASE):
        raise ParseError("Nacos 集群节点输出格式非法")
    value = sum(1 for line in lines if re.search(r"\"?alive\"?\s*[:=]\s*(?:true|1)", line, re.IGNORECASE))
    return {"value": value, "summary": f"nacos_alive_nodes={value}"}


def parse_nacos_mysql_connectivity(output):
    return _typed_bool(output, r"spring\.sql\.init\.platform|db\.url\.0|succeeded|open", negative=r"connection refused|failed|error|not found")


def parse_nacos_error_log(output):
    return _typed_count(output, r"OutOfMemory|No DataSource|SQLException|Connection refused|FATAL|\bERROR\b|raft.*failed", summary="nacos_error_log_hits={value}")


def parse_rabbitmq_service_health(output):
    return _typed_bool(output, r"beam\.smp|rabbitmq-server|\bactive\b", negative=r"inactive|failed|not found|error")


def parse_rabbitmq_node_health(output):
    return _typed_bool(output, r"Ping succeeded|pong|running_applications|rabbit", negative=r"timeout|failed|error|not running")


def parse_rabbitmq_cluster_nodes(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    if not re.search(r"rabbit@[-A-Za-z0-9_.]+|running_nodes", text, re.IGNORECASE):
        raise ParseError("RabbitMQ 集群节点输出格式非法")
    value = len(set(re.findall(r"rabbit@[-A-Za-z0-9_.]+", text, re.IGNORECASE)))
    return {"value": value, "summary": f"rabbitmq_running_nodes={value}"}


def parse_rabbitmq_alarm_partition(output):
    return _typed_bool(output, r"no alarms|partitions\s*:\s*\[?\s*\]?", negative=r"memory alarm|disk alarm|partition|\balarm\b")


def parse_rabbitmq_queue_backlog(output):
    lines = _typed_middleware_lines(output)
    values = [int(x) for x in re.findall(r"(?:messages(?:_ready|_unacknowledged)?|backlog)\s*[=:]?\s*([0-9]+)", "\n".join(lines), re.IGNORECASE)]
    if not values:
        raise ParseError("RabbitMQ 队列积压数值缺失")
    value = max(values)
    return {"value": value, "summary": f"rabbitmq_queue_backlog={value}"}


def parse_rabbitmq_connection_pressure(output):
    lines = _typed_middleware_lines(output)
    values = [int(x) for x in re.findall(r"(?:send_pend|messages_unacknowledged)\s*[=:]?\s*([0-9]+)", "\n".join(lines), re.IGNORECASE)]
    if not values:
        raise ParseError("RabbitMQ 连接压力数值缺失")
    value = max(values)
    return {"value": value, "summary": f"rabbitmq_connection_pressure={value}"}


def parse_redis_service_health(output):
    return _typed_bool(output, r"redis-server|\bactive\b", negative=r"inactive|failed|not found|error")


def parse_redis_ping_version(output):
    return _typed_bool(output, r"\bPONG\b|redis_version:", negative=r"NOAUTH|connection refused|timeout|error")


def parse_redis_replication_health(output):
    return _typed_bool(output, r"role:(?:master|slave)|master_link_status:up", negative=r"master_link_status:down|fail|error")


def parse_redis_sentinel_health(output):
    return _typed_bool(output, r"master|sentinel_masters|num-slaves", negative=r"s_down|o_down|disconnected|fail")


def parse_redis_cluster_health(output):
    return _typed_bool(output, r"cluster_state:ok|cluster_slots_ok:16384", negative=r"fail|noaddr|cluster_state:fail")


def parse_redis_persistence_health(output):
    return _typed_bool(output, r"loading:0|aof_enabled:1|appendfsync.*everysec", negative=r"aof_last_write_status:err|error|failed")


def parse_rocketmq_namesrv_health(output):
    return _typed_bool(output, r"NamesrvStartup|mqnamesrv|start(?:ed|up)", negative=r"inactive|failed|error")


def parse_rocketmq_broker_health(output):
    return _typed_bool(output, r"BrokerStartup|mqbroker|start(?:ed|up)", negative=r"FATAL|\bERROR\b|failed")


def parse_rocketmq_core_ports_health(output):
    return _typed_count(output, r":(?:9876|9877|10911|10912)\b.*LISTEN", summary="rocketmq_listening_ports={value}")


def parse_rocketmq_cluster_registration(output):
    return _typed_bool(output, r"BrokerName|Master|clusterName", negative=r"broker.*missing|failed|error")


def parse_rocketmq_controller_sync_set(output):
    return _typed_bool(output, r"leader|SyncStateSet|controller", negative=r"no leader|failed|error")


def parse_rocketmq_consumer_lag(output):
    lines = _typed_middleware_lines(output)
    values = [int(x) for x in re.findall(r"(?:diff|lag|behind)\s*[=:]?\s*([0-9]+)", "\n".join(lines), re.IGNORECASE)]
    if not values:
        raise ParseError("RocketMQ 消费堆积数值缺失")
    value = max(values)
    return {"value": value, "summary": f"rocketmq_consumer_lag={value}"}


def parse_tomcat_service_health(output):
    return _typed_bool(output, r"org\.apache\.catalina\.startup\.Bootstrap|active", negative=r"failed|inactive|not found")


def parse_tomcat_http_health(output):
    return _typed_count(output, r":(?:8080|8443|8005)\b.*LISTEN", summary="tomcat_listening_ports={value}")


def parse_tomcat_access_log_errors(output):
    return _typed_count(output, r"SEVERE|Exception|OutOfMemoryError|Address already in use", summary="tomcat_error_log_hits={value}")


def parse_tomcat_jvm_memory(output):
    lines = _typed_middleware_lines(output)
    match = re.search(r"^\s*\d+\s+(\d+)\s+\d+\s+[0-9.]+\s+", "\n".join(lines), re.MULTILINE)
    if not match:
        match = re.search(r"rss\s*[=:]\s*(\d+)", "\n".join(lines), re.IGNORECASE)
    if not match:
        raise ParseError("Tomcat JVM RSS 数值缺失")
    value = round(int(match.group(1)) / 1024.0, 2)
    return {"value": value, "summary": f"tomcat_rss={value}MB"}


def parse_tomcat_thread_pool_pressure(output):
    return _typed_number(output, r"\bfd\s*=\s*(\d+)", cast=int, summary="tomcat_open_fds={value}")


def parse_tomcat_security_baseline(output):
    return _typed_bool(
        output,
        r"<Server|<Connector|autoDeploy\s*=\s*[\"']?false|deployOnStartup\s*=\s*[\"']?false|server\s*=",
        negative=r"autoDeploy\s*=\s*[\"']?true|deployOnStartup\s*=\s*[\"']?true|failed|error",
    )


def parse_keepalived_vip_present(output):
    return _typed_bool(output, r"\bUP\b.*\b(?:inet|[0-9]{1,3}(?:\.[0-9]{1,3}){3})\b|virtual_ipaddress", negative=r"\bDOWN\b|missing|not found|error")


def parse_keepalived_vrrp_role(output):
    return _typed_bool(output, r"\b(?:MASTER|BACKUP)\b.*(?:priority|interface|virtual_router_id)|state\s+(?:MASTER|BACKUP)", negative=r"\bFAULT\b|double master|error")


def parse_keepalived_health_check_status(output):
    return _typed_bool(output, r"track_script|healthcheck|script", negative=r"not found|failed|permission denied|error")


def parse_keepalived_failover_config(output):
    lines = _typed_middleware_lines(output)
    text = "\n".join(lines)
    markers = ("notify_master", "notify_backup", "virtual_ipaddress", "track_script")
    present = [marker for marker in markers if re.search(marker, text, re.IGNORECASE)]
    if not present:
        raise ParseError("Keepalived 故障切换配置输出格式非法")
    value = len(present) == len(markers)
    return {"value": value, "summary": f"keepalived_failover_config={str(value).lower()}"}


# --------------------------------------------------------------------------
# 解析器注册表（metrics.py parser 字段名 ↔ 函数；TD §5.2 按名注册）
# --------------------------------------------------------------------------

PARSERS: Dict[str, Any] = {
    "local.process.present": parse_process_present,
    "local.service.active": parse_service_active,
    "local.port.listening": parse_port_listening,
    "local.cpu.utilization": parse_cpu_utilization,
    "local.cpu.load_1m": parse_cpu_load_1m,
    "local.memory.available_percent": parse_memory_available_percent,
    "local.swap.used_percent": parse_swap_used_percent,
    "local.filesystem.used_percent": parse_filesystem_used_percent,
    "local.filesystem.inode_used_percent": parse_filesystem_inode_used_percent,
    "local.logs.key_evidence": parse_logs_key_evidence,
    "local.nginx.process.present": parse_process_present,
    "local.nginx.version": parse_nginx_version,
    "local.nginx.config.valid": parse_nginx_config_valid,
    "local.nginx.port.listening": parse_nginx_port_listening,
    "local.nginx.error_log.key_evidence": parse_nginx_error_log,
    "local.nginx.connections.status": parse_nginx_connections_status,
    "local.nginx.access_log.status_codes": parse_nginx_access_log_status_codes,
    "local.nginx.config.baseline": parse_nginx_config_baseline,
    "local.nginx.security.baseline": parse_nginx_security_baseline,
    "local.nginx.http.reachability": parse_nginx_http_reachability,
    "local.nginx.stub_status.connections": parse_nginx_stub_status_connections,
    "local.nginx.proxy.upstream.config": parse_nginx_proxy_upstream_config,
    "local.nginx.fd.process.limits": parse_nginx_fd_process_limits,
    "local.nginx.https.certificate": parse_nginx_https_certificate,
    "local.keepalived.process.present": parse_process_present,
    "local.keepalived.version": parse_keepalived_version,
    "local.keepalived.vip.bound": parse_keepalived_vip_bound,
    "local.keepalived.vip.access": parse_keepalived_vip_access,
    "local.keepalived.config.baseline": parse_keepalived_config_baseline,
    "local.keepalived.healthcheck.script": parse_keepalived_healthcheck,
    "local.keepalived.error_log.key_evidence": parse_keepalived_error_log,
    "local.keepalived.capability.stability": parse_keepalived_capability_stability,
    "local.elasticsearch.process.present": parse_process_present,
    "local.elasticsearch.version": parse_elasticsearch_version,
    "local.elasticsearch.cluster.health": parse_elasticsearch_cluster_health,
    "local.elasticsearch.nodes.online": parse_elasticsearch_nodes,
    "local.elasticsearch.nodes.cpu": parse_elasticsearch_nodes_cpu,
    "local.elasticsearch.nodes.memory": parse_elasticsearch_nodes_memory,
    "local.elasticsearch.nodes.disk": parse_elasticsearch_nodes_disk,
    "local.elasticsearch.disk.watermark": parse_elasticsearch_watermark,
    "local.elasticsearch.shards.unassigned": parse_elasticsearch_shards,
    "local.elasticsearch.service.port": parse_elasticsearch_service_port,
    "local.elasticsearch.heap.gc": parse_elasticsearch_heap_gc,
    "local.elasticsearch.thread_pool.rejected": parse_elasticsearch_thread_pool,
    "local.elasticsearch.cluster.settings": parse_elasticsearch_cluster_settings,
    "local.elasticsearch.discovery.config": parse_elasticsearch_discovery_config,
    "local.elasticsearch.indices.health": parse_elasticsearch_indices,
    "local.elasticsearch.slowlog.key_evidence": parse_elasticsearch_slowlog,
    "local.elasticsearch.security.accounts": parse_elasticsearch_security,
    "local.elasticsearch.certificate.validity": parse_elasticsearch_certificate,
    "local.elasticsearch.snapshot.repository": parse_elasticsearch_snapshot,
    "local.elasticsearch.system.parameters": parse_elasticsearch_system_parameters,
}

for _metric in metrics_registry.METRICS:
    _parser_name = _metric.get("parser")
    if _parser_name == "parse_middleware_text":
        PARSERS[_metric["metric_id"]] = parse_middleware_text
    elif _parser_name in globals():
        PARSERS[_metric["metric_id"]] = globals()[_parser_name]

# parser 字段名与注册表一一对应（tests 机械校验）
PARSER_NAMES = {m["metric_id"]: m["parser"] for m in metrics_registry.METRICS}


# --------------------------------------------------------------------------
# 四状态判定（HR §4 不可变顺序；阈值数值来自 MR §5/§6 已批准基线）
# --------------------------------------------------------------------------


def _compare(value: float, op: str, threshold: float) -> bool:
    """override 判定表达式求值（TD §6.2 op 集合）。"""
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return value == threshold
    if op == "!=":
        return value != threshold
    raise ValueError(f"未知判定 op: {op!r}")


def _apply_external_rules(
    metric_id: str, normalized: Optional[float], resolved: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """外部配置层（HR §4 步骤 2）：规则按声明顺序首个匹配生效（TD §6.2）。

    normalized 为 None（非数值指标）→ 数值规则无法应用 → 不判定；
    规则未命中 → 返回 None，由调用方回退文档基线（并记录 provenance 注记）。
    """
    if resolved.get("layer") != LAYER_EXTERNAL_CONFIG:
        return None
    if normalized is None:
        return None
    for rule in resolved.get("rules", []):
        if rule.get("range") is not None:
            lo, hi = rule["range"]
            if lo <= normalized <= hi:
                return rule
        elif rule.get("op") is not None and _compare(normalized, rule["op"], rule["value"]):
            return rule
    return None


def _baseline_rule(resolved: Dict[str, Any], status: str) -> Optional[Dict[str, Any]]:
    """文档基线层已定义边界（resolved.rules 中 status 对应条目）。"""
    for rule in resolved.get("rules", []):
        if rule.get("status") == status:
            return rule
    return None


def _unknown_decision(resolved: Dict[str, Any], extra_note: Optional[str] = None) -> Dict[str, Any]:
    """无规则/冲突层（HR §4 步骤 4）：→ UNKNOWN，threshold.notes 注明原因。"""
    unknown = resolved.get("unknown") or {"reason": "missing", "note": None}
    note = unknown.get("note")
    if extra_note:
        note = "；".join(x for x in (extra_note, note) if x)
    return {"status": STATUS_UNKNOWN, "note": note}


def _judge_process_present(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """进程存在 → OK；进程缺失 → CRIT（故障）（MR §5.1 文档基线）。"""
    if parsed["present"]:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}


def _judge_service_active(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """active → OK；非 active → CRIT（故障）（MR §5.2 文档基线）。

    systemctl 的 unknown/not-found 同属“非 active”（MR §5.2：非 active/
    进程不存在 → CRIT）。
    """
    if parsed["active_state"].lower() == "active":
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}


def _judge_port_listening(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """端口监听（MR §5.3 / TD §5.2 判定入口）。

    判据（profile ports 为配置边界，C13）：
      - profile 无端口配置 → UNKNOWN（missing，C13）；
      - profile 端口未全部监听 → CRIT（不监听，故障）；
      - 模式外端口仍开放（C7）→ WARN（需确认）；
      - 其余 → OK（监听且进程匹配——v1 以监听行进程名非空为匹配口径，
        完整模式核对属 profile 扩展，见报告 D5）。
    """
    profile_ports = (profile or {}).get("ports")
    if not profile_ports:
        return _unknown_decision(resolved, extra_note="端口/模式无配置（C13）")
    profile_set = set(int(p) for p in profile_ports)
    listen_set = set(parsed["ports"])
    missing = profile_set - listen_set
    if missing:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    extra = listen_set - profile_set
    if extra:
        return {
            "status": STATUS_WARN,
            "rule": _baseline_rule(resolved, STATUS_WARN),
            "note": f"模式外端口仍开放（C7 需确认）: {sorted(extra)}",
        }
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_cpu_utilization(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """CPU 使用率（MR §5.4 / TD §5.2；单次采样口径，见报告 D4）。

    文档基线（v=us+sy）：
      - v < 70 → OK（长期<70% 且波动<80%）；
      - 70 ≤ v < 80 → OK（单次采样满足“短时波动<80%”；“长期<70%”需
        两次采样确认，首版单次采样，provenance 注记）；
      - 80 ≤ v ≤ 90 → WARN（持续>80%）；
      - v > 90 → WARN + 注记（“>90% 且伴随业务证据”→CRIT 需业务证据
        采集能力，首版无此能力，按 TD §5.2 保持 WARN）。
    """
    v = parsed["total"]
    if v < 70:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    if v < 80:
        return {
            "status": STATUS_OK,
            "rule": _baseline_rule(resolved, STATUS_OK),
            "note": "单次采样满足“短时波动<80%”；“长期<70%”需两次采样"
                    "（间隔≥60s）确认，首版为单次采样",
        }
    if v <= 90:
        return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}
    return {
        "status": STATUS_WARN,
        "rule": _baseline_rule(resolved, STATUS_WARN),
        "note": ">90% 且伴随业务证据 → CRIT；首版无业务证据采集能力，"
                "按 TD §5.2 保持 WARN",
    }


def _judge_cpu_load_1m(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """系统负载（MR §5.5 / TD §5.2）。

      - 核数不可得 → UNKNOWN（missing，判据不可用）；
      - load_1m ≤ 核数 → OK；
      - load_1m > 核数 → 告警等级缺失（C5）→ UNKNOWN（外部配置可覆盖）。
    """
    if parsed["nproc"] is None:
        return _unknown_decision(resolved, extra_note="核数无法获取，判据不可用")
    if parsed["load_1m"] <= parsed["nproc"]:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return _unknown_decision(resolved)


def _judge_memory_available_percent(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """可用内存百分比（MR §5.6 / TD §5.2）。

      - ≥20% → OK；10% ≤ available_percent < 20% → WARN；<10% → CRIT。
    """
    pct = parsed["pct"]
    if pct >= 20:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    if pct < 10:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}


def _judge_swap_used_percent(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Swap 使用率（MR §5.7 / TD §5.2）。

      - used=0 或未配置 → OK（全部手册一致）；
      - used>0 → 判据冲突未解决（C3）→ UNKNOWN（外部配置可覆盖）。
    """
    if parsed["used"] == 0:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return _unknown_decision(resolved)


def _judge_filesystem_used_percent(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """磁盘使用率（MR §5.8 / TD §5.2 75/85/95 分层）。

      - <75% → OK（Nginx/Tomcat <80% 为 C1 建议线差异，外部配置覆盖）；
      - 75–85% → WARN；>85% → CRIT（>95% 故障风险、ES >90% 严重告警层
        C6 并入 CRIT）。
    """
    v = parsed["max_pct"]
    if v < 75:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    if v <= 85:
        return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}
    note = ">95% 故障风险；ES >90% 严重告警层并入 CRIT（C6）" if v > 95 else None
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT), "note": note}


def _judge_filesystem_inode_used_percent(
    parsed: Dict[str, Any],
    resolved: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """inode 使用率（MR §5.9 / TD §5.2）。

      - <80% → OK（全部手册一致）；
      - ≥80% → 数值边界缺失（C5）→ UNKNOWN（外部配置可覆盖）。
    """
    if parsed["max_pct"] < 80:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return _unknown_decision(resolved)


def _judge_logs_key_evidence(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """关键日志证据（MR §5.10 / TD §5.2）。

      - 无命中 → OK（无新增不可解释 ERROR/FATAL）；
      - 有命中 → 关键词等级判定（隐患级/故障级）按产品手册、冲突未解决
        （C10）→ UNKNOWN（外部配置可按命中数覆盖，normalized_value=命中数）。
    """
    if parsed["hit_count"] == 0:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return _unknown_decision(
        resolved, extra_note="命中但关键词等级判定未解决（C10 冲突）"
    )


# -- local.nginx.* 判定（nginx-p0-v1 文档基线）--------------------------------


def _judge_nginx_config_valid(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """配置语法通过 → OK；语法失败/文件缺失/端口冲突/权限错误 → CRIT（故障）。"""
    if parsed["valid"]:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}


def _judge_nginx_version(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """实际运行版本必须命中 inspect.conf nginx_version 候选值。"""
    expected = [
        str(item).strip()
        for item in (profile or {}).get("nginx_version", [])
        if str(item).strip()
    ]
    actual = str(parsed.get("version") or "")
    if not expected:
        return _unknown_decision(resolved, extra_note="inspect.conf 未配置 nginx_version 版本基线")
    note = f"实际版本={actual}；允许版本={'、'.join(expected)}"
    if actual in expected:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK), "note": note}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT), "note": note}


def _judge_nginx_port_listening(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """端口监听且本地可访问 → OK；不监听/连接失败/5xx → CRIT（故障）。"""
    if not parsed["listening"]:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    status = parsed["http_status"]
    if status is None or status >= 500:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_nginx_error_log(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """无关键错误命中 → OK；命中 → WARN（记录时间点与错误内容，优先处理）。"""
    if parsed["hit_count"] == 0:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}


def _judge_nginx_connections_status(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """stub_status 开启且返回连接数 → OK；未开启 → UNKNOWN（记录为未配置）。"""
    if not parsed["configured"]:
        return _unknown_decision(
            resolved, extra_note="stub_status 未开启或 URL 不可访问（记录为未配置）"
        )
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_nginx_access_log_status_codes(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """5xx=0 → OK；5xx>0 → WARN（记录 URL/来源 IP/状态码/时间段，关联 error.log）。"""
    if parsed["five_xx"] == 0:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}


_NGINX_CORE_DIRECTIVES = frozenset(
    {"worker_processes", "worker_connections", "keepalive_timeout"}
)


def _judge_nginx_config_baseline(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """核心指令齐全 → OK；配置漂移/缺失 → WARN（记录差异与变更依据）。"""
    missing = sorted(_NGINX_CORE_DIRECTIVES - set(parsed["directives"]))
    if not missing:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {
        "status": STATUS_WARN,
        "rule": _baseline_rule(resolved, STATUS_WARN),
        "note": "配置漂移：缺失核心指令 " + "、".join(missing),
    }


def _judge_nginx_security_baseline(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """按 inspect.conf nginx_baseline 检查安全指令；缺失项 → WARN。"""
    requested = ["server_tokens_off", "autoindex_off"]
    if profile and profile.get("nginx_baseline"):
        configured: List[str] = []
        for item in profile.get("nginx_baseline") or []:
            match = re.fullmatch(r"([A-Za-z0-9_]+)=(True|False|true|false)", str(item))
            if match and match.group(2).lower() == "true":
                configured.append(match.group(1))
        if configured:
            requested = configured
    missing = [name for name in requested if not parsed.get(name, False)]
    if not missing:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {
        "status": STATUS_WARN,
        "rule": _baseline_rule(resolved, STATUS_WARN),
        "note": "安全配置缺失（未满足 inspect.conf nginx_baseline: "
        + "、".join(missing)
        + "）",
    }


def _judge_nginx_http_reachability(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """A response is reachable; explicit HTTP 5xx is a service failure."""
    status = parsed.get("http_status")
    if not parsed.get("reachable") or status is None:
        return _unknown_decision(resolved, extra_note="无法取得 HTTP 状态码")
    if int(status) >= 500:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_nginx_stub_status_connections(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """stub_status availability is factual; no capacity threshold is invented."""
    if not parsed.get("configured"):
        return _unknown_decision(resolved, extra_note="stub_status 未配置或不可访问")
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_nginx_proxy_upstream_config(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Keep upstream/proxy evidence without inventing health thresholds."""
    return _unknown_decision(resolved, extra_note="upstream/proxy 配置边界未定义")


_NGINX_FD_NOFILE_OK = 65535
_NGINX_FD_NOFILE_WARN = 32768
_NGINX_MAX_PROCESSES_OK = 4096
_NGINX_MAX_PROCESSES_WARN = 2048
_NGINX_FD_PROCESS_PRODUCT_NOTE = (
    "产品补充阈值（用户授权；非 DOCX-derived）："
    "nofile >=65535 OK、32768..65534 WARN、<32768 CRIT；"
    "max_processes >=4096 OK、2048..4095 WARN、<2048 CRIT；"
    "两维按最高严重度聚合。"
)


def _judge_nginx_fd_process_limits(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Apply the user-authorized product thresholds to both limit dimensions."""
    nofile = parsed.get("nofile")
    max_processes = parsed.get("max_processes")
    if (
        not isinstance(nofile, int)
        or isinstance(nofile, bool)
        or not isinstance(max_processes, int)
        or isinstance(max_processes, bool)
        or nofile < 0
        or max_processes < 0
    ):
        return _unknown_decision(
            resolved,
            extra_note=_NGINX_FD_PROCESS_PRODUCT_NOTE + "；字段缺失或无效，无法判定。",
        )

    def _status(value: int, ok_floor: int, warn_floor: int) -> str:
        if value >= ok_floor:
            return STATUS_OK
        if value >= warn_floor:
            return STATUS_WARN
        return STATUS_CRIT

    statuses = [
        _status(nofile, _NGINX_FD_NOFILE_OK, _NGINX_FD_NOFILE_WARN),
        _status(max_processes, _NGINX_MAX_PROCESSES_OK, _NGINX_MAX_PROCESSES_WARN),
    ]
    severity = {STATUS_OK: 0, STATUS_WARN: 1, STATUS_CRIT: 2}
    status = max(statuses, key=lambda item: severity[item])
    return {
        "status": status,
        "rule": _baseline_rule(resolved, status),
        "note": (
            f"{_NGINX_FD_PROCESS_PRODUCT_NOTE} "
            f"当前 nofile={nofile}、max_processes={max_processes}。"
        ),
    }


def _judge_nginx_https_certificate(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Keep certificate evidence without inventing validity-age thresholds."""
    return _unknown_decision(resolved, extra_note="HTTPS 证书有效期边界未定义")


# -- local.keepalived.* 判定（keepalived-p0-v1） -----------------------------


def _judge_keepalived_version(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    expected = [
        str(item).strip()
        for item in (profile or {}).get("keepalived_version", [])
        if str(item).strip()
    ]
    actual = str(parsed.get("version") or "")
    if not expected:
        return _unknown_decision(resolved, extra_note="inspect.conf 未配置 keepalived_version 版本基线")
    note = f"实际版本={actual}；允许版本={'、'.join(expected)}"
    if actual in expected:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK), "note": note}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT), "note": note}


def _judge_keepalived_vip_bound(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    state = parsed.get("state")
    bound = bool(parsed.get("bound"))
    if state == "MASTER" and bound:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    if state == "BACKUP" and not bound:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {
        "status": STATUS_CRIT,
        "rule": _baseline_rule(resolved, STATUS_CRIT),
        "note": f"配置角色={state}；配置 VIP={'、'.join(parsed.get('expected_vips', []))}；当前持有={'、'.join(parsed.get('bound_vips', [])) or '无'}",
    }


def _judge_keepalived_vip_access(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    status = parsed.get("http_status")
    if status is None:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    if status >= 500:
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


_KEEPALIVED_CONFIG_DIRECTIVES = frozenset(
    {"state", "interface", "virtual_router_id", "priority", "advert_int",
     "virtual_ipaddress", "script", "track_script"}
)


def _judge_keepalived_config_baseline(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    missing = sorted(_KEEPALIVED_CONFIG_DIRECTIVES - set(parsed.get("directives", [])))
    if not missing:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {
        "status": STATUS_WARN,
        "rule": _baseline_rule(resolved, STATUS_WARN),
        "note": "配置基线缺失关键项：" + "、".join(missing),
    }


def _judge_keepalived_healthcheck(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if parsed.get("present") and parsed.get("executable"):
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}


def _judge_keepalived_error_log(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if parsed.get("fault_count", 0) or parsed.get("script_failure_count", 0):
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    if parsed.get("transition_count", 0) >= 3:
        return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_keepalived_capability_stability(
    parsed: Dict[str, Any], resolved: Dict[str, Any], profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if not parsed.get("log_available"):
        return _unknown_decision(resolved, extra_note="Keepalived 日志不可用，无法判断漂移稳定性")
    if not parsed.get("has_net_admin") or not parsed.get("has_net_raw"):
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    if parsed.get("fault_count", 0) or parsed.get("script_failure_count", 0):
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    if parsed.get("transition_count", 0) >= 3:
        return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


# -- local.elasticsearch.* 判定（elasticsearch-p0-p1-v1） -------------------


def _judge_elasticsearch_version(parsed, resolved, profile=None):
    expected = [str(x).strip() for x in (profile or {}).get("elasticsearch_version", []) if str(x).strip()]
    if not expected:
        return _unknown_decision(resolved, extra_note="inspect.conf 未配置 elasticsearch_version 版本基线")
    actual = str(parsed.get("version") or "")
    if actual in expected:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK), "note": f"实际版本={actual}；允许版本={'、'.join(expected)}"}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT), "note": f"实际版本={actual}；允许版本={'、'.join(expected)}"}


def _judge_es_cluster_health(parsed, resolved, profile=None):
    expected_values = (profile or {}).get("elasticsearch_expected_nodes", [])
    expected = int(expected_values[0]) if expected_values else 0
    if parsed["status"] == "red" or (expected and parsed["nodes"] <= expected - 2):
        return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}
    if parsed["status"] == "yellow" or (expected and parsed["nodes"] < expected) or parsed["active_shards_percent"] < 100:
        return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN)}
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_es_nodes_online(parsed, resolved, profile=None):
    expected = int((profile or {}).get("elasticsearch_expected_nodes", [0])[0] or 0)
    if not expected:
        return _unknown_decision(resolved, extra_note="未配置 elasticsearch_expected_nodes")
    missing = expected - int(parsed["count"])
    if missing <= 0:
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_WARN if missing == 1 else STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_WARN if missing == 1 else STATUS_CRIT)}


def _judge_es_nodes_cpu(parsed, resolved, profile=None):
    value = parsed["max_cpu"]
    status = STATUS_OK if value < 80 else STATUS_WARN if value <= 90 else STATUS_CRIT
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_nodes_memory(parsed, resolved, profile=None):
    if parsed["max_heap"] > 85 or parsed["max_ram"] > 95:
        status = STATUS_CRIT
    elif parsed["max_heap"] >= 75 or parsed["max_ram"] >= 90:
        status = STATUS_WARN
    else:
        status = STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_nodes_disk(parsed, resolved, profile=None):
    value = parsed["max_disk"]
    status = STATUS_OK if value < 75 else STATUS_WARN if value <= 85 else STATUS_CRIT
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_watermark(parsed, resolved, profile=None):
    if not any(parsed.get("watermarks", {}).values()):
        return _unknown_decision(resolved, extra_note="未读取到 Elasticsearch low/high/flood_stage 水位线")
    return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}


def _judge_es_shards(parsed, resolved, profile=None):
    if parsed["unassigned_primary"]:
        status = STATUS_CRIT
    elif parsed["unassigned_replica"] or parsed["initializing"]:
        status = STATUS_WARN
    else:
        status = STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_service_port(parsed, resolved, profile=None):
    discovered = parsed.get("expected_ports") or []
    ports = set(discovered) or {
        int(x) for x in (profile or {}).get("elasticsearch_http_port", ["9200"])
    } | {
        int(x) for x in (profile or {}).get("elasticsearch_transport_port", ["9300"])
    }
    if not ports:
        return _unknown_decision(resolved, extra_note="HTTP/Transport 端口未配置")
    if parsed["process"] and ports.issubset(set(parsed["ports"])):
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_CRIT, "rule": _baseline_rule(resolved, STATUS_CRIT)}


def _judge_es_heap_gc(parsed, resolved, profile=None):
    if parsed.get("oom"):
        status = STATUS_CRIT
    elif parsed.get("max_heap") is not None and parsed["max_heap"] > 85:
        status = STATUS_CRIT
    elif parsed.get("full_gc") or (parsed.get("max_heap") is not None and parsed["max_heap"] >= 75):
        status = STATUS_WARN
    else:
        status = STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_thread_pool(parsed, resolved, profile=None):
    status = STATUS_OK if parsed["queue"] == 0 and parsed["rejected"] == 0 else STATUS_WARN
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_cluster_settings(parsed, resolved, profile=None):
    status = STATUS_WARN if parsed.get("restricted") else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_discovery_config(parsed, resolved, profile=None):
    expected = [str(x) for x in (profile or {}).get("elasticsearch_seed_hosts", [])]
    joined = " ".join(parsed.get("seed_hosts", []))
    if expected and all(item.split(":", 1)[0] in joined for item in expected):
        if parsed.get("initial_master_nodes"):
            return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN), "note": "集群已运行时仍保留 cluster.initial_master_nodes，请确认是否应删除"}
        return {"status": STATUS_OK, "rule": _baseline_rule(resolved, STATUS_OK)}
    return {"status": STATUS_WARN, "rule": _baseline_rule(resolved, STATUS_WARN), "note": "seed_hosts 与 inspect.conf 规划节点不完全一致"}


def _judge_es_indices(parsed, resolved, profile=None):
    status = STATUS_CRIT if parsed["red"] else STATUS_WARN if parsed["yellow"] else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_slowlog(parsed, resolved, profile=None):
    status = STATUS_WARN if parsed["hit_count"] else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status), "note": "未启用慢日志时按未配置说明展示，不默认判定为故障" if not parsed["files"] else None}


def _judge_es_security(parsed, resolved, profile=None):
    status = STATUS_WARN if parsed["superusers"] > 1 else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_certificate(parsed, resolved, profile=None):
    days = parsed["days_remaining"]
    status = STATUS_CRIT if days <= 0 else STATUS_WARN if days < 30 else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_snapshot(parsed, resolved, profile=None):
    status = STATUS_OK if parsed["repository_count"] > 0 and parsed["verify_ok"] else STATUS_WARN
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_es_system_parameters(parsed, resolved, profile=None):
    critical = parsed["max_map_count"] < 262144 or parsed["nofile"] < 65535 or parsed["nproc"] < 4096
    warning = parsed.get("swap_used") not in (None, 0) or str(parsed["memlock"]).lower() not in {"unlimited", "-1"}
    status = STATUS_CRIT if critical else STATUS_WARN if warning else STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


def _judge_middleware_text(parsed, resolved, profile=None):
    if parsed.get("has_critical_marker"):
        status = STATUS_CRIT
    elif parsed.get("has_warning_marker"):
        status = STATUS_WARN
    else:
        status = STATUS_OK
    return {"status": status, "rule": _baseline_rule(resolved, status)}


_MIDDLEWARE_NUMERIC_THRESHOLDS = {
    "local.kafka.under_replicated_partitions": (0, 2),
    "local.kafka.under_min_isr": (0, 0),
    "local.kafka.zookeeper.latency": (50, 200),
    "local.mysql.replication.lag": (0, 30),
    "local.mysql.connection.pressure": (80, 95),
    "local.nacos.cluster.nodes": (2, 1),
    "local.nacos.core_ports.health": (4, 2),
    "local.rocketmq.core_ports.health": (4, 2),
    "local.tomcat.http.health": (3, 2),
    "local.nacos.error_log": (0, 10),
    "local.tomcat.access_log.errors": (0, 10),
    "local.rabbitmq.cluster.nodes": (3, 2),
    "local.rabbitmq.queue.backlog": (100, 1000),
    "local.rabbitmq.connection.pressure": (100, 1000),
    "local.rocketmq.consumer.lag": (0, 100),
    "local.tomcat.jvm.memory": (2048, 4096),
    "local.tomcat.thread_pool.pressure": (10000, 50000),
}


def _judge_typed_middleware(parsed, resolved, profile=None):
    value = parsed.get("value")
    metric_id = parsed.get("metric_id")
    if isinstance(value, bool):
        status = STATUS_OK if value else STATUS_CRIT
    else:
        thresholds = _MIDDLEWARE_NUMERIC_THRESHOLDS.get(metric_id)
        if thresholds is None:
            status = STATUS_UNKNOWN
        else:
            ok_limit, warn_limit = thresholds
            if metric_id in {
                "local.nacos.cluster.nodes",
                "local.nacos.core_ports.health",
                "local.rocketmq.core_ports.health",
                "local.tomcat.http.health",
            }:
                status = STATUS_OK if value >= ok_limit else STATUS_WARN if value >= warn_limit else STATUS_CRIT
            elif metric_id == "local.rabbitmq.cluster.nodes":
                status = STATUS_OK if value >= ok_limit else STATUS_WARN if value >= warn_limit else STATUS_CRIT
            else:
                status = STATUS_OK if value <= ok_limit else STATUS_WARN if value <= warn_limit else STATUS_CRIT
    return {"status": status, "rule": _baseline_rule(resolved, status)}


# 指标 → 判定函数（数值边界全部来自 MR §5/§6 已批准基线）
JUDGERS: Dict[str, Any] = {
    "local.process.present": _judge_process_present,
    "local.service.active": _judge_service_active,
    "local.port.listening": _judge_port_listening,
    "local.cpu.utilization": _judge_cpu_utilization,
    "local.cpu.load_1m": _judge_cpu_load_1m,
    "local.memory.available_percent": _judge_memory_available_percent,
    "local.swap.used_percent": _judge_swap_used_percent,
    "local.filesystem.used_percent": _judge_filesystem_used_percent,
    "local.filesystem.inode_used_percent": _judge_filesystem_inode_used_percent,
    "local.logs.key_evidence": _judge_logs_key_evidence,
    "local.nginx.process.present": _judge_process_present,
    "local.nginx.version": _judge_nginx_version,
    "local.nginx.config.valid": _judge_nginx_config_valid,
    "local.nginx.port.listening": _judge_nginx_port_listening,
    "local.nginx.error_log.key_evidence": _judge_nginx_error_log,
    "local.nginx.connections.status": _judge_nginx_connections_status,
    "local.nginx.access_log.status_codes": _judge_nginx_access_log_status_codes,
    "local.nginx.config.baseline": _judge_nginx_config_baseline,
    "local.nginx.security.baseline": _judge_nginx_security_baseline,
    "local.nginx.http.reachability": _judge_nginx_http_reachability,
    "local.nginx.stub_status.connections": _judge_nginx_stub_status_connections,
    "local.nginx.proxy.upstream.config": _judge_nginx_proxy_upstream_config,
    "local.nginx.fd.process.limits": _judge_nginx_fd_process_limits,
    "local.nginx.https.certificate": _judge_nginx_https_certificate,
    "local.keepalived.process.present": _judge_process_present,
    "local.keepalived.version": _judge_keepalived_version,
    "local.keepalived.vip.bound": _judge_keepalived_vip_bound,
    "local.keepalived.vip.access": _judge_keepalived_vip_access,
    "local.keepalived.config.baseline": _judge_keepalived_config_baseline,
    "local.keepalived.healthcheck.script": _judge_keepalived_healthcheck,
    "local.keepalived.error_log.key_evidence": _judge_keepalived_error_log,
    "local.keepalived.capability.stability": _judge_keepalived_capability_stability,
    "local.elasticsearch.process.present": _judge_process_present,
    "local.elasticsearch.version": _judge_elasticsearch_version,
    "local.elasticsearch.cluster.health": _judge_es_cluster_health,
    "local.elasticsearch.nodes.online": _judge_es_nodes_online,
    "local.elasticsearch.nodes.cpu": _judge_es_nodes_cpu,
    "local.elasticsearch.nodes.memory": _judge_es_nodes_memory,
    "local.elasticsearch.nodes.disk": _judge_es_nodes_disk,
    "local.elasticsearch.disk.watermark": _judge_es_watermark,
    "local.elasticsearch.shards.unassigned": _judge_es_shards,
    "local.elasticsearch.service.port": _judge_es_service_port,
    "local.elasticsearch.heap.gc": _judge_es_heap_gc,
    "local.elasticsearch.thread_pool.rejected": _judge_es_thread_pool,
    "local.elasticsearch.cluster.settings": _judge_es_cluster_settings,
    "local.elasticsearch.discovery.config": _judge_es_discovery_config,
    "local.elasticsearch.indices.health": _judge_es_indices,
    "local.elasticsearch.slowlog.key_evidence": _judge_es_slowlog,
    "local.elasticsearch.security.accounts": _judge_es_security,
    "local.elasticsearch.certificate.validity": _judge_es_certificate,
    "local.elasticsearch.snapshot.repository": _judge_es_snapshot,
    "local.elasticsearch.system.parameters": _judge_es_system_parameters,
}

for _metric in metrics_registry.METRICS:
    if _metric.get("parser") == "parse_middleware_text":
        JUDGERS[_metric["metric_id"]] = _judge_middleware_text


def _typed_judger(metric_id):
    def judge(parsed, resolved, profile=None):
        typed = dict(parsed)
        typed["metric_id"] = metric_id
        return _judge_typed_middleware(typed, resolved, profile)
    return judge


for _metric in metrics_registry.METRICS:
    if (
        _is_typed_middleware_metric(_metric.get("metric_id", ""))
        and _metric.get("parser") != "parse_middleware_text"
    ):
        JUDGERS[_metric["metric_id"]] = _typed_judger(_metric["metric_id"])

# 数值化指标（normalized_value 非 null，可参与外部配置数值规则；MR §5）
NUMERIC_METRIC_IDS = frozenset(
    {
        "local.cpu.utilization",
        "local.cpu.load_1m",
        "local.memory.available_percent",
        "local.swap.used_percent",
        "local.filesystem.used_percent",
        "local.filesystem.inode_used_percent",
        "local.logs.key_evidence",
        "local.nginx.error_log.key_evidence",
        "local.nginx.connections.status",
        "local.nginx.access_log.status_codes",
        "local.keepalived.error_log.key_evidence",
        "local.elasticsearch.nodes.online",
        "local.elasticsearch.nodes.cpu",
        "local.elasticsearch.nodes.memory",
        "local.elasticsearch.nodes.disk",
        "local.elasticsearch.shards.unassigned",
        "local.elasticsearch.heap.gc",
        "local.elasticsearch.thread_pool.rejected",
        "local.elasticsearch.indices.health",
        "local.elasticsearch.slowlog.key_evidence",
        "local.elasticsearch.security.accounts",
        "local.elasticsearch.certificate.validity",
        "local.elasticsearch.system.parameters",
        "local.kafka.under_replicated_partitions",
        "local.kafka.under_min_isr",
        "local.kafka.zookeeper.latency",
        "local.mysql.replication.lag",
        "local.mysql.connection.pressure",
        "local.nacos.cluster.nodes",
        "local.rabbitmq.cluster.nodes",
        "local.rabbitmq.queue.backlog",
        "local.rabbitmq.connection.pressure",
        "local.rocketmq.consumer.lag",
        "local.tomcat.jvm.memory",
        "local.tomcat.thread_pool.pressure",
    }
)


# --------------------------------------------------------------------------
# metric 对象构建
# --------------------------------------------------------------------------


def _normalized_value(metric_id: str, parsed: Dict[str, Any]) -> Optional[float]:
    """规范化数值（统一单位可比较；MR §5 各指标计算列；非数值 → None）。"""
    if metric_id == "local.cpu.utilization":
        return float(parsed["total"])
    if metric_id == "local.cpu.load_1m":
        return float(parsed["load_1m"])
    if metric_id == "local.memory.available_percent":
        return float(parsed["pct"])
    if metric_id == "local.swap.used_percent":
        return float(parsed["pct"])
    if metric_id == "local.filesystem.used_percent":
        return float(parsed["max_pct"])
    if metric_id == "local.filesystem.inode_used_percent":
        return float(parsed["max_pct"])
    if metric_id == "local.logs.key_evidence":
        return float(parsed["hit_count"])
    if metric_id == "local.nginx.error_log.key_evidence":
        return float(parsed["hit_count"])
    if metric_id == "local.nginx.connections.status":
        return float(parsed["active"]) if parsed["configured"] else None
    if metric_id == "local.nginx.access_log.status_codes":
        return float(parsed["five_xx"])
    if metric_id == "local.keepalived.error_log.key_evidence":
        return float(parsed["hit_count"])
    if metric_id == "local.elasticsearch.nodes.online":
        return float(parsed["count"])
    if metric_id == "local.elasticsearch.nodes.cpu":
        return float(parsed["max_cpu"])
    if metric_id == "local.elasticsearch.nodes.memory":
        return float(parsed["max_heap"])
    if metric_id == "local.elasticsearch.nodes.disk":
        return float(parsed["max_disk"])
    if metric_id == "local.elasticsearch.shards.unassigned":
        return float(parsed["unassigned_primary"] + parsed["unassigned_replica"])
    if metric_id == "local.elasticsearch.heap.gc":
        return float(parsed["max_heap"]) if parsed.get("max_heap") is not None else None
    if metric_id == "local.elasticsearch.thread_pool.rejected":
        return float(parsed["rejected"])
    if metric_id == "local.elasticsearch.indices.health":
        return float(parsed["count"])
    if metric_id == "local.elasticsearch.slowlog.key_evidence":
        return float(parsed["hit_count"])
    if metric_id == "local.elasticsearch.security.accounts":
        return float(parsed["superusers"])
    if metric_id == "local.elasticsearch.certificate.validity":
        return float(parsed["days_remaining"])
    if metric_id == "local.elasticsearch.system.parameters":
        return float(parsed["max_map_count"])
    if _is_typed_middleware_metric(metric_id):
        value = parsed.get("value")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return None


def _raw_value(metric_id: str, parsed: Dict[str, Any]) -> Any:
    """原始值（字符串化保留原文格式；HR §3.1 raw_value）。"""
    if metric_id == "local.process.present":
        return "present" if parsed["present"] else "absent"
    if metric_id == "local.service.active":
        return parsed["active_state"]
    if metric_id == "local.port.listening":
        return ",".join(str(p) for p in parsed["ports"])
    if metric_id == "local.cpu.utilization":
        return str(parsed["total"])
    if metric_id == "local.cpu.load_1m":
        return str(parsed["load_1m"])
    if metric_id == "local.memory.available_percent":
        return str(parsed["pct"])
    if metric_id == "local.swap.used_percent":
        return str(parsed["pct"])
    if metric_id == "local.filesystem.used_percent":
        return str(parsed["max_pct"])
    if metric_id == "local.filesystem.inode_used_percent":
        return str(parsed["max_pct"])
    if metric_id == "local.logs.key_evidence":
        return str(parsed["hit_count"])
    if metric_id == "local.nginx.process.present":
        return "present" if parsed["present"] else "absent"
    if metric_id == "local.nginx.version":
        return parsed["version"]
    if metric_id == "local.nginx.config.valid":
        return "valid" if parsed["valid"] else "invalid"
    if metric_id == "local.nginx.port.listening":
        status = "null" if parsed["http_status"] is None else str(parsed["http_status"])
        return f"listening={parsed['listening']};http_status={status}"
    if metric_id == "local.nginx.error_log.key_evidence":
        return str(parsed["hit_count"])
    if metric_id == "local.nginx.connections.status":
        if not parsed["configured"]:
            return "not_configured"
        return (f"active={parsed['active']};reading={parsed['reading']};"
                f"writing={parsed['writing']};waiting={parsed['waiting']}")
    if metric_id == "local.nginx.access_log.status_codes":
        return str(parsed["five_xx"])
    if metric_id == "local.nginx.config.baseline":
        return ";".join(parsed["directives"])
    if metric_id == "local.nginx.security.baseline":
        return (f"server_tokens_off={parsed['server_tokens_off']};"
                f"autoindex_off={parsed['autoindex_off']}")
    if metric_id == "local.nginx.http.reachability":
        return f"reachable={parsed['reachable']};http_status={parsed['http_status']}"
    if metric_id == "local.nginx.stub_status.connections":
        if not parsed["configured"]:
            return "not_configured"
        return (f"active={parsed['active']};reading={parsed['reading']};"
                f"writing={parsed['writing']};waiting={parsed['waiting']}")
    if metric_id == "local.nginx.proxy.upstream.config":
        return (f"upstreams={','.join(parsed['upstreams'])};"
                f"proxy_passes={','.join(parsed['proxy_passes'])};"
                f"proxy_set_headers={','.join(parsed['proxy_set_headers'])}")
    if metric_id == "local.nginx.fd.process.limits":
        return f"nofile={parsed['nofile']};max_processes={parsed['max_processes']}"
    if metric_id == "local.nginx.https.certificate":
        return (f"certificates={','.join(parsed['certificates'])};"
                f"not_after={','.join(parsed['not_after'])}")
    if metric_id == "local.keepalived.process.present":
        return "present" if parsed["present"] else "absent"
    if metric_id == "local.keepalived.version":
        return parsed["version"]
    if metric_id == "local.keepalived.vip.bound":
        return f"state={parsed['state']};bound={parsed['bound']}"
    if metric_id == "local.keepalived.vip.access":
        status = "null" if parsed["http_status"] is None else str(parsed["http_status"])
        return f"reachable={parsed['reachable']};http_status={status}"
    if metric_id == "local.keepalived.config.baseline":
        return ";".join(parsed["directives"])
    if metric_id == "local.keepalived.healthcheck.script":
        return parsed.get("script") or "not_configured"
    if metric_id == "local.keepalived.error_log.key_evidence":
        return str(parsed["hit_count"])
    if metric_id == "local.keepalived.capability.stability":
        return f"net_admin={parsed['has_net_admin']};net_raw={parsed['has_net_raw']}"
    if metric_id == "local.elasticsearch.process.present":
        return "present" if parsed["present"] else "absent"
    if _is_typed_middleware_metric(metric_id):
        return parsed.get("value")
    if metric_id == "local.elasticsearch.version":
        return parsed["version"]
    if metric_id == "local.elasticsearch.cluster.health":
        return parsed["summary"]
    if metric_id == "local.elasticsearch.nodes.online":
        return str(parsed["count"])
    if metric_id == "local.elasticsearch.nodes.cpu":
        return str(parsed["max_cpu"])
    if metric_id == "local.elasticsearch.nodes.memory":
        return f"heap={parsed['max_heap']};ram={parsed['max_ram']}"
    if metric_id == "local.elasticsearch.nodes.disk":
        return str(parsed["max_disk"])
    if metric_id == "local.elasticsearch.disk.watermark":
        return ";".join(f"{k}={v}" for k, v in parsed["watermarks"].items())
    if metric_id == "local.elasticsearch.shards.unassigned":
        return f"primary={parsed['unassigned_primary']};replica={parsed['unassigned_replica']};initializing={parsed['initializing']}"
    if metric_id == "local.elasticsearch.service.port":
        expected = ",".join(map(str, parsed.get("expected_ports", [])))
        return f"process={parsed['process']};ports={','.join(map(str, parsed['ports']))};expected={expected}"
    if metric_id == "local.elasticsearch.heap.gc":
        return f"heap={parsed.get('max_heap')};full_gc={parsed['full_gc']};oom={parsed['oom']}"
    if metric_id == "local.elasticsearch.thread_pool.rejected":
        return f"queue={parsed['queue']};rejected={parsed['rejected']}"
    if metric_id == "local.elasticsearch.cluster.settings":
        return "restricted" if parsed["restricted"] else "clean"
    if metric_id == "local.elasticsearch.discovery.config":
        return f"seed_hosts={len(parsed['seed_hosts'])};initial_master_nodes={bool(parsed['initial_master_nodes'])}"
    if metric_id == "local.elasticsearch.indices.health":
        return f"indices={parsed['count']};red={parsed['red']};yellow={parsed['yellow']}"
    if metric_id == "local.elasticsearch.slowlog.key_evidence":
        return f"files={parsed['files']};hits={parsed['hit_count']}"
    if metric_id == "local.elasticsearch.security.accounts":
        return f"users={parsed['users']};superusers={parsed['superusers']}"
    if metric_id == "local.elasticsearch.certificate.validity":
        return f"days_remaining={parsed['days_remaining']:.1f};expiry={parsed['expiry']}"
    if metric_id == "local.elasticsearch.snapshot.repository":
        return f"repositories={parsed['repository_count']};verify={parsed['verify_ok']}"
    if metric_id == "local.elasticsearch.system.parameters":
        return f"max_map_count={parsed['max_map_count']};swap_used={parsed['swap_used']};nofile={parsed['nofile']};nproc={parsed['nproc']};memlock={parsed['memlock']}"
    return None


def _filesystem_detail_status(
    metric_id: str,
    used_percent: float,
    resolved: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    """按单个挂载点数值复用现有阈值判定，返回该明细自身状态。

    指标整体仍以 parsed["max_pct"] 判定；这里仅把单行值临时作为
    max_pct 传给同一判定函数，避免复制或发明阈值。外部配置规则同样
    先按声明顺序匹配，未命中时沿用现有的文档基线回退语义。
    """
    value = float(used_percent)
    matched_rule = _apply_external_rules(metric_id, value, resolved)
    if matched_rule is not None:
        return str(matched_rule["status"])
    if resolved.get("layer") == LAYER_EXTERNAL_CONFIG:
        resolved = _fallback_to_baseline(resolved, metric_id)
    detail_parsed = {"max_pct": value}
    return str(JUDGERS[metric_id](detail_parsed, resolved, profile)["status"])


def _cpu_load_detail_decision(
    load: float,
    parsed: Dict[str, Any],
    resolved: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """为单个负载时间窗口生成状态和人类可读判定说明。

    判定仍复用现有 1 分钟负载规则：负载不高于 CPU 核数为 OK；超过核数
    的告警等级在文档中未定义，默认 UNKNOWN。渲染层只读取这里落盘的结果。
    """
    detail_parsed = dict(parsed)
    detail_parsed["load_1m"] = float(load)
    decision = _judge_cpu_load_1m(detail_parsed, resolved, profile)
    status = str(decision["status"])
    if parsed.get("nproc") is None:
        judgement = "CPU 核数无法获取：无法判定"
    elif float(load) <= int(parsed["nproc"]):
        judgement = "负载 <= CPU 核数：正常"
    else:
        judgement = "负载 > CPU 核数：告警等级未定义，暂为 UNKNOWN"
    return {"status": status, "judgement": judgement}


def _evidence_details(
    metric_id: str,
    parsed: Dict[str, Any],
    resolved: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """返回可直接被报表消费的结构化证据明细。

    文件系统指标保存挂载点级状态；系统负载指标保存 1/5/15 分钟窗口、
    CPU 核数和对应判定。``normalized_value``/``raw_value`` 仍保持旧的
    1 分钟负载兼容语义。
    """
    if metric_id == "local.cpu.load_1m":
        rows: List[Dict[str, Any]] = []
        for window, key in (("1 分钟", "load_1m"), ("5 分钟", "load_5m"), ("15 分钟", "load_15m")):
            decision = _cpu_load_detail_decision(parsed[key], parsed, resolved, profile)
            rows.append(
                {
                    "window": window,
                    "load": float(parsed[key]),
                    "cpu_cores": parsed["nproc"],
                    "status": decision["status"],
                    "judgement": decision["judgement"],
                }
            )
        return rows
    if metric_id not in {
        "local.filesystem.used_percent",
        "local.filesystem.inode_used_percent",
    }:
        return None
    return [
        {
            "filesystem": mask_output(str(row["filesystem"])),
            "mount": mask_output(str(row["mount"])),
            "used_percent": int(row["pct"]),
            "status": _filesystem_detail_status(
                metric_id, row["pct"], resolved, profile
            ),
        }
        for row in parsed.get("rows", [])
    ]


def _output_summary(metric_id: str, parsed: Dict[str, Any]) -> str:
    """evidence.output_summary（已脱敏；HR §3.1 evidence.output_summary）。"""
    if metric_id == "local.process.present":
        if not parsed["present"]:
            return "未匹配到进程（absent）"
        return "；".join(parsed["summary"])
    if metric_id == "local.service.active":
        parts = [f"ActiveState={parsed['active_state']}"]
        if parsed.get("substate") is not None:
            parts.append(f"SubState={parsed['substate']}")
        return " ".join(parts)
    if metric_id == "local.port.listening":
        return "；".join(r["line"] for r in parsed["rows"])
    if metric_id == "local.cpu.utilization":
        return (
            f"%Cpu(s): {parsed['us']} us, {parsed['sy']} sy"
            f"（us+sy={parsed['total']}）; top-rows={parsed['top_rows']}"
        )
    if metric_id == "local.cpu.load_1m":
        nproc = parsed["nproc"] if parsed["nproc"] is not None else "N/A"
        return (
            f"load_1m={parsed['load_1m']} load_5m={parsed['load_5m']} "
            f"load_15m={parsed['load_15m']} nproc={nproc}"
        )
    if metric_id == "local.memory.available_percent":
        return f"available={parsed['available']}MB total={parsed['total']}MB → {parsed['pct']}%"
    if metric_id == "local.swap.used_percent":
        if not parsed["configured"]:
            return "未配置 Swap（total=0/无 Swap 行）→ 0%"
        return f"used={parsed['used']}MB total={parsed['total']}MB → {parsed['pct']}%"
    if metric_id == "local.filesystem.used_percent":
        rows = "；".join(
            f"{r['filesystem']} {r['pct']}%（{r['mount']}）" for r in parsed["rows"]
        )
        return f"max={parsed['max_pct']}%；{rows}"
    if metric_id == "local.filesystem.inode_used_percent":
        rows = "；".join(
            f"{r['filesystem']} {r['pct']}%（{r['mount']}）" for r in parsed["rows"]
        )
        return f"max={parsed['max_pct']}%；{rows}"
    if metric_id == "local.logs.key_evidence":
        dist = " ".join(f"{k}={v}" for k, v in sorted(parsed["keyword_counts"].items()))
        last = " / ".join(parsed["last_hits"]) if parsed["last_hits"] else "无命中"
        return f"hits={parsed['hit_count']}；{dist}；最近命中: {last}"
    if metric_id == "local.nginx.process.present":
        if not parsed["present"]:
            return "未匹配到 Nginx 进程（absent）"
        return "；".join(parsed["summary"])
    if metric_id == "local.nginx.version":
        return parsed["version"]
    if metric_id == "local.nginx.config.valid":
        if parsed["valid"]:
            return "nginx -t：syntax is ok + test is successful"
        return "nginx -t：配置校验失败（" + " / ".join(parsed["summary"]) + "）"
    if metric_id == "local.nginx.port.listening":
        status = "null" if parsed["http_status"] is None else str(parsed["http_status"])
        return f"listening={parsed['listening']}；http_status={status}"
    if metric_id == "local.nginx.error_log.key_evidence":
        dist = " ".join(f"{k}={v}" for k, v in sorted(parsed["keyword_counts"].items()))
        last = " / ".join(parsed["last_hits"]) if parsed["last_hits"] else "无命中"
        return f"hits={parsed['hit_count']}；{dist}；最近命中: {last}"
    if metric_id == "local.nginx.connections.status":
        if not parsed["configured"]:
            return "stub_status 未开启或 URL 不可访问（记录为未配置）"
        return (f"active={parsed['active']} reading={parsed['reading']} "
                f"writing={parsed['writing']} waiting={parsed['waiting']}")
    if metric_id == "local.nginx.access_log.status_codes":
        dist = " ".join(f"{k}={v}" for k, v in sorted(parsed["counts"].items()))
        last = " / ".join(parsed["last_hits"]) if parsed["last_hits"] else "无 5xx"
        return f"5xx={parsed['five_xx']}；{dist}；最近 5xx: {last}"
    if metric_id == "local.nginx.config.baseline":
        return "核心指令: " + ("、".join(parsed["directives"]) if parsed["directives"] else "无命中")
    if metric_id == "local.nginx.security.baseline":
        return (f"server_tokens off={parsed['server_tokens_off']}；"
                f"autoindex off={parsed['autoindex_off']}")
    if metric_id == "local.nginx.http.reachability":
        return f"reachable={parsed['reachable']}；http_status={parsed['http_status']}"
    if metric_id == "local.nginx.stub_status.connections":
        if not parsed["configured"]:
            return "stub_status 未配置或 URL 不可访问；记录为未配置"
        return (f"active={parsed['active']} reading={parsed['reading']} "
                f"writing={parsed['writing']} waiting={parsed['waiting']}")
    if metric_id == "local.nginx.proxy.upstream.config":
        return (f"upstreams={','.join(parsed['upstreams'])}；"
                f"proxy_pass={','.join(parsed['proxy_passes'])}；"
                f"proxy_set_header={','.join(parsed['proxy_set_headers'])}")
    if metric_id == "local.nginx.fd.process.limits":
        return f"nofile={parsed['nofile']}；max_processes={parsed['max_processes']}"
    if metric_id == "local.nginx.https.certificate":
        return (f"certificates={','.join(parsed['certificates'])}；"
                f"notAfter={','.join(parsed['not_after'])}")
    if metric_id == "local.keepalived.process.present":
        if not parsed["present"]:
            return "未匹配到 Keepalived 进程（absent）"
        return "；".join(parsed["summary"])
    if metric_id == "local.keepalived.version":
        return parsed["version"]
    if metric_id == "local.keepalived.vip.bound":
        return (
            f"state={parsed['state']}；配置VIP={'、'.join(parsed['expected_vips'])}；"
            f"当前持有={'、'.join(parsed['bound_vips']) or '无'}"
        )
    if metric_id == "local.keepalived.vip.access":
        status = "null" if parsed["http_status"] is None else str(parsed["http_status"])
        return f"targets={'、'.join(parsed['targets'])}；http_status={status}"
    if metric_id == "local.keepalived.config.baseline":
        return "关键指令: " + ("、".join(parsed["directives"]) if parsed["directives"] else "无命中")
    if metric_id == "local.keepalived.healthcheck.script":
        return f"script={parsed.get('script') or '未配置'}；可执行={parsed.get('executable', False)}"
    if metric_id == "local.keepalived.error_log.key_evidence":
        last = " / ".join(parsed["last_hits"]) if parsed["last_hits"] else "无命中"
        return (
            f"hits={parsed['hit_count']}；MASTER/BACKUP切换={parsed['transition_count']}；"
            f"FAULT={parsed['fault_count']}；脚本失败={parsed['script_failure_count']}；最近命中: {last}"
        )
    if metric_id == "local.keepalived.capability.stability":
        return (
            f"cap_net_admin={parsed['has_net_admin']}；cap_net_raw={parsed['has_net_raw']}；"
            f"切换={parsed['transition_count']}；FAULT={parsed['fault_count']}；"
            f"脚本失败={parsed['script_failure_count']}"
        )
    if metric_id.startswith("local.elasticsearch."):
        if metric_id == "local.elasticsearch.process.present":
            return "发现 Elasticsearch 进程" if parsed["present"] else "未发现 Elasticsearch 进程"
        if metric_id == "local.elasticsearch.version":
            return parsed["version"]
        if metric_id == "local.elasticsearch.cluster.health":
            return parsed["summary"]
        if metric_id == "local.elasticsearch.nodes.online":
            return f"在线节点={parsed['count']}；" + " / ".join(parsed.get("summary", []))
        if metric_id == "local.elasticsearch.nodes.cpu":
            return f"节点数={parsed['count']}；最大CPU={parsed['max_cpu']:.1f}%；平均CPU={parsed['avg_cpu']:.1f}%"
        if metric_id == "local.elasticsearch.nodes.memory":
            return f"节点数={parsed['count']}；最大heap={parsed['max_heap']:.1f}%；最大ram={parsed['max_ram']:.1f}%"
        if metric_id == "local.elasticsearch.nodes.disk":
            return f"节点数={parsed['count']}；最大disk.percent={parsed['max_disk']:.1f}%"
        if metric_id == "local.elasticsearch.disk.watermark":
            return "水位线：" + "; ".join(f"{k}={v}" for k, v in parsed["watermarks"].items())
        if metric_id == "local.elasticsearch.shards.unassigned":
            return f"主分片未分配={parsed['unassigned_primary']}；副本未分配={parsed['unassigned_replica']}；初始化中={parsed['initializing']}"
        if metric_id == "local.elasticsearch.service.port":
            expected = ",".join(map(str, parsed.get("expected_ports", []))) or "配置端口未知"
            return f"进程={parsed['process']}；监听端口={','.join(map(str, parsed['ports'])) or '无'}；期望端口={expected}"
        if metric_id == "local.elasticsearch.heap.gc":
            return f"最大heap={parsed.get('max_heap')}; Full GC命中={parsed['full_gc']}；OOM命中={parsed['oom']}"
        if metric_id == "local.elasticsearch.thread_pool.rejected":
            return f"queue={parsed['queue']}；rejected={parsed['rejected']}"
        if metric_id == "local.elasticsearch.cluster.settings":
            return "存在限制性动态设置" if parsed["restricted"] else "未发现限制性动态设置"
        if metric_id == "local.elasticsearch.discovery.config":
            return f"seed_hosts={len(parsed['seed_hosts'])}；cluster.initial_master_nodes={'存在' if parsed['initial_master_nodes'] else '不存在'}"
        if metric_id == "local.elasticsearch.indices.health":
            return f"索引数={parsed['count']}；red={parsed['red']}；yellow={parsed['yellow']}"
        if metric_id == "local.elasticsearch.slowlog.key_evidence":
            return f"慢日志文件={parsed['files']}；命中={parsed['hit_count']}"
        if metric_id == "local.elasticsearch.security.accounts":
            return f"用户对象={parsed['users']}；superuser 命中={parsed['superusers']}"
        if metric_id == "local.elasticsearch.certificate.validity":
            return f"到期时间={parsed['expiry']}；剩余约 {parsed['days_remaining']:.1f} 天"
        if metric_id == "local.elasticsearch.snapshot.repository":
            return f"仓库数量={parsed['repository_count']}；verify={parsed['verify_ok']}"
        if metric_id == "local.elasticsearch.system.parameters":
            return f"max_map_count={parsed['max_map_count']}；swap_used={parsed['swap_used']}；nofile={parsed['nofile']}；nproc={parsed['nproc']}；memlock={parsed['memlock']}"
    if _is_typed_middleware_metric(metric_id):
        return parsed.get("summary", "")
    return ""


def _metric_definition(metric_id: str) -> Dict[str, Any]:
    """指标定义（metrics.py 注册表；缺失 → ValueError 防御）。"""
    m = metrics_registry.get_metric(metric_id)
    if m is None:
        raise ValueError(f"指标注册表缺少定义: {metric_id}")
    return m


def _scope_for(metric_id: str) -> str:
    """指标 scope：Nginx 指标归 nginx-p0-v1，其余走 linux-common-p0-v1。"""
    if metric_id.startswith("local.nginx."):
        return "nginx-p0-v1"
    if metric_id.startswith("local.keepalived."):
        return "keepalived-p0-v1"
    if metric_id.startswith("local.elasticsearch."):
        return "elasticsearch-p0-p1-v1"
    for _prefix in (
        "local.kafka.", "local.mysql.", "local.nacos.", "local.rabbitmq.",
        "local.redis.", "local.rocketmq.", "local.tomcat.",
    ):
        if metric_id.startswith(_prefix):
            return _prefix[6:-1] + "-p0-p1-v1"
    return SCOPE


# Marker used to preserve legacy documents when no replay field was supplied.
_REPLAY_NOT_SUPPLIED = object()


def _normalized_replay_field(value: Any = _REPLAY_NOT_SUPPLIED) -> Dict[str, Any]:
    """Return an optional replay field only for an explicit safe value.

    ``evidence.command`` is intentionally not a source here.  Invalid explicit
    values are dropped fail-closed; an explicit JSON null is preserved as null.
    """
    if value is _REPLAY_NOT_SUPPLIED:
        return {}
    if value is None:
        return {"replay_command": None}
    safe = normalize_replay_command(value)
    return {"replay_command": safe} if safe is not None else {}


def _build_metric_document(
    metric_id: str,
    *,
    status: str,
    raw_value: Any,
    normalized_value: Optional[float],
    threshold: Dict[str, Any],
    evidence: Dict[str, Any],
    error: Optional[Dict[str, Any]],
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    """按 HR §3 组装 metric 对象（字段顺序即 schema 顺序，便于人工核对）。"""
    m = _metric_definition(metric_id)
    return {
        "metric_id": metric_id,
        "name": m["name"],
        "scope": _scope_for(metric_id),
        "status": status,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "unit": m["unit"],
        "threshold": threshold,
        "evidence": evidence,
        "error": error,
        "provenance": provenance,
    }


def _error_metric_document(
    metric_id: str,
    error: Dict[str, str],
    *,
    inspection_id: str,
    collected_at: str,
    command: Optional[str] = None,
    replay_command: Any = _REPLAY_NOT_SUPPLIED,
) -> Dict[str, Any]:
    """采集层失败（error 已由 ansible_runner 分类）→ UNKNOWN + error（HR §3.2）。

    不参与业务判定：threshold 全 null（HR §7 示例），error.metric_status=UNKNOWN。
    """
    m = _metric_definition(metric_id)
    evidence = {
        "command": command or m["command"],
        "output_summary": None,
        "raw_ref": f"raw/{metric_id}.out",
        "sampled_at": collected_at,
    }
    evidence.update(_normalized_replay_field(replay_command))
    provenance = {
        "config_sources": [],
        "doc_sources": [m["source_anchor"]],
        "notes": error["message"],
    }
    return _build_metric_document(
        metric_id,
        status=STATUS_UNKNOWN,
        raw_value=None,
        normalized_value=None,
        threshold=dict(_NULL_THRESHOLD),
        evidence=evidence,
        error={
            "code": error["code"],
            "message": error["message"],
            "metric_status": METRIC_ERROR_STATUS,
        },
        provenance=provenance,
    )


def _judged_metric_document(
    metric_id: str,
    parsed: Dict[str, Any],
    decision: Dict[str, Any],
    resolved: Dict[str, Any],
    *,
    inspection_id: str,
    collected_at: str,
    profile: Optional[Dict[str, Any]] = None,
    command: Optional[str] = None,
    replay_command: Any = _REPLAY_NOT_SUPPLIED,
) -> Dict[str, Any]:
    """判定完成 → 组装 threshold/provenance（HR §3 字段语义，REQ-D-04 可追溯）。"""
    status = decision["status"]
    rule = decision.get("rule")
    note = decision.get("note")
    unknown = resolved.get("unknown") or {}
    doc_sources = list(resolved.get("provenance", {}).get("doc_sources", []))
    config_sources = list(resolved.get("provenance", {}).get("config_sources", []))
    # resolved.provenance.notes：外部配置回退文档基线等判定链注记
    # （_fallback_to_baseline），notes 空时透传到 metric 层保证可追溯
    resolved_notes = resolved.get("provenance", {}).get("notes")

    if status == STATUS_UNKNOWN:
        threshold = {
            "layer": LAYER_UNRESOLVED,
            "rule_id": None,
            "value": None,
            "source_anchor": doc_sources[0] if doc_sources else None,
            "notes": note,
        }
        provenance = {
            "config_sources": config_sources,
            "doc_sources": doc_sources,
            "notes": note or resolved_notes,
        }
    elif rule is not None:
        threshold = {
            "layer": LAYER_DOCUMENT_BASELINE,
            "rule_id": rule["rule_id"],
            "value": rule["rule"],
            "source_anchor": doc_sources[0] if doc_sources else None,
            "notes": note,
        }
        provenance = {
            "config_sources": config_sources,
            "doc_sources": doc_sources,
            "notes": note or resolved_notes,
        }
    else:
        # 基线未定义该边界（防御；本基线 10 指标 OK/WARN/CRIT 均有定义）
        threshold = {
            "layer": LAYER_UNRESOLVED,
            "rule_id": None,
            "value": None,
            "source_anchor": doc_sources[0] if doc_sources else None,
            "notes": note or unknown.get("note") or "文档基线未定义该边界",
        }
        provenance = {
            "config_sources": config_sources,
            "doc_sources": doc_sources,
            "notes": note or unknown.get("note") or resolved_notes,
        }

    evidence = {
        "command": command or _metric_definition(metric_id)["command"],
        "output_summary": mask_output(_output_summary(metric_id, parsed)),
        "raw_ref": f"raw/{metric_id}.out",
        "sampled_at": collected_at,
    }
    evidence.update(_normalized_replay_field(replay_command))
    details = _evidence_details(metric_id, parsed, resolved, profile)
    if details is not None:
        evidence["details"] = details
    return _build_metric_document(
        metric_id,
        status=status,
        raw_value=_raw_value(metric_id, parsed),
        normalized_value=_normalized_value(metric_id, parsed),
        threshold=threshold,
        evidence=evidence,
        error=None,
        provenance=provenance,
    )


# --------------------------------------------------------------------------
# 主机级规范化（ansible_runner 主机结果 → host-result-v1 文档）
# --------------------------------------------------------------------------


def _id_safe_host_token(host_name: str) -> str:
    """host 键 → inspection_id 合法后缀（安全字符集占位映射，T-104F）。

    业务字段脱敏产物是 `<IP>`/`<REDACTED>`，二者不在 schema pattern
    （^insp-[0-9]{14}-[A-Za-z0-9_.-]+$）字符集内——若派生 ID 直接交给
    _sweep_strings 强制扫描，IP/凭据关键字会被替换成这两个占位而破坏
    pattern（validate_host_result 拒绝 → 事实源落盘 exit 10）。因此派生
    标识符先用安全占位（ip/redacted）完成与脱敏同序（先 IP 后凭据）的
    映射，剩余非 [A-Za-z0-9_.-] 字符替换为 `-`；映射结果不再被
    mask_output 匹配（对 _sweep_strings 幂等），host 名本身的脱敏仍由
    _sweep_strings 按 `<IP>`/`<REDACTED>` 处理。
    """
    text = _IPV4_RE.sub(_ID_IP_PLACEHOLDER, host_name)
    text = _IPV6_RE.sub(_ID_IP_PLACEHOLDER, text)
    text = _CRED_VALUE_RE.sub(_ID_CRED_PLACEHOLDER, text)
    text = _JVM_PROP_RE.sub(_ID_CRED_PLACEHOLDER, text)
    text = _URL_USERINFO_RE.sub(
        lambda m: m.group(1) + _ID_CRED_PLACEHOLDER + "@", text
    )
    text = _CLI_FLAG_RE.sub(_ID_CRED_PLACEHOLDER, text)
    text = _BARE_CRED_RE.sub(_ID_CRED_PLACEHOLDER, text)
    return re.sub(r"[^A-Za-z0-9_.-]", "-", text)


def make_inspection_id(host_name: str, when: Optional[datetime] = None) -> str:
    """inspection_id = insp-<yyyyMMddHHmmss>-<host>（HR §2 格式）。

    host 键先做安全字符集映射（IP→ip、凭据特征→redacted、其余非
    [A-Za-z0-9_.-] 字符→`-`），保证 ID 必匹配 schema pattern 且不被
    文档级强制脱敏扫描改写（T-104F：派生标识符不使用 `<IP>`/`<REDACTED>`，
    那会破坏 pattern → 事实源落盘 exit 10）。
    """
    when = when or datetime.now()
    safe_host = _id_safe_host_token(host_name)
    return f"insp-{when:%Y%m%d%H%M%S}-{safe_host}"


def _now_iso() -> str:
    """本地时区 ISO8601（schema pattern ^[0-9]{4}-…T）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _error_host_document(
    host_result: Dict[str, Any],
    *,
    run_id: str,
    inspection_id: str,
    collected_at: str,
    inventory_source: str,
    product_profiles: List[str],
    meta: Dict[str, Any],
    duration_sec: float,
) -> Dict[str, Any]:
    """主机级 ERROR（连接失败/探测失败）：无业务结论（AE §6，REQ-E-07）。

    技术失败计数保留在 execution_summary（executed=0/failed=planned）；
    host_error 明细由 fact_source 汇总索引承载（事实源 schema 无主机级
    error 字段，见报告 D1）。
    """
    planned = int(host_result.get("summary", {}).get("total", 0))
    failed = int(host_result.get("summary", {}).get("failed", planned))
    return {
        "schema": "host-result-v1",
        "schema_version": 1,
        "run_id": run_id,
        "inspection_id": inspection_id,
        "host": {
            "name": host_result.get("host", host_result.get("name", "")),
            "ip": mask_output(str(host_result.get("ip", ""))),
            "inventory_source": inventory_source,
            "product_profiles": product_profiles,
        },
        "collected_at": collected_at,
        "duration_sec": duration_sec,
        "execution_status": STATUS_ERROR,
        "execution_summary": {
            "total_metrics": planned,
            "ok": 0,
            "warn": 0,
            "crit": 0,
            "unknown": 0,
            "executed": 0,
            "failed": failed,
        },
        "metrics": [],
        "meta": dict(meta),
    }


def _parser_input(metric_id: str, metric_result: Mapping[str, Any]) -> str:
    """Return the parser input while preserving command output channels.

    ``nginx -t`` writes its successful validation messages to stderr.  Ansible
    correctly keeps stdout/stderr separate, so feeding stdout only makes a
    valid configuration look invalid.  Other parsers retain the historical
    stdout-only behavior because their commands use stdout as the data stream.
    """
    stdout = str(metric_result.get("stdout") or "")
    if metric_id != "local.nginx.config.valid":
        return stdout
    stderr = str(metric_result.get("stderr") or "")
    if not stderr:
        return stdout
    if stdout and not stdout.endswith("\n"):
        stdout += "\n"
    return stdout + stderr


def normalize_host_result(
    host_result: Dict[str, Any],
    *,
    run_id: str,
    inspection_id: Optional[str] = None,
    collected_at: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    product_profiles: Optional[Sequence[str]] = None,
    resolved_thresholds: Optional[Dict[str, Dict[str, Any]]] = None,
    inventory_source: str = "local",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """单主机原始结果 → host-result-v1 文档（HR §2/§3/§4 全流程）。

    参数：
      host_result         T-103 ansible_runner 主机级结果
                          （{host, ip, probe, probe_status, host_error,
                          execution_status, metrics[], summary, duration_sec}）；
      run_id              运行 ID（如 run-20260814-001）；
      inspection_id       缺省由 make_inspection_id(host, collected_at) 生成；
      collected_at        采集时间（ISO8601；缺省当前时间）；
      profile             产品 profile（config 的 profiles 单产品值；端口
                          判据等配置边界）；None → 相关判据走 UNKNOWN；
      product_profiles    主机适用的产品 profile 名列表（HR §2 host 字段）；
      resolved_thresholds config.build_resolved_thresholds() 结果
                          （缺省自动加载文档基线、无 override）；
      inventory_source    HR §2 host.inventory_source（缺省 "local"）；
      meta                HR §2 meta（缺省 DEFAULT_META）。

    返回：host-result-v1 文档（已强制脱敏扫描；validate_host_result 可校验）。
    """
    if resolved_thresholds is None:
        resolved_thresholds = config_mod.build_resolved_thresholds()
    collected_at = collected_at or _now_iso()
    if inspection_id is None:
        try:
            when = datetime.fromisoformat(collected_at)
        except ValueError:
            when = datetime.now()
        inspection_id = make_inspection_id(str(host_result.get("host", "host")), when)
    meta = dict(meta) if meta is not None else dict(DEFAULT_META)
    product_profiles = list(product_profiles or [])
    duration_sec = float(host_result.get("duration_sec", 0.0) or 0.0)

    host_error = host_result.get("host_error")
    probe_ok = host_result.get("probe_status") == "ok"
    if host_error is not None or not probe_ok:
        doc = _error_host_document(
            host_result,
            run_id=run_id,
            inspection_id=inspection_id,
            collected_at=collected_at,
            inventory_source=inventory_source,
            product_profiles=product_profiles,
            meta=meta,
            duration_sec=duration_sec,
        )
        return _sweep_strings(doc)

    metric_results = list(host_result.get("metrics", []))
    metric_docs: List[Dict[str, Any]] = []
    for mres in metric_results:
        metric_id = mres.get("metric_id")
        if metric_id not in PARSERS:
            # 未注册指标（防御）：按 PARSE_FAILED 语义处理（指标注册表无该
            # 定义，用占位元数据直接构建，避免中断整机文档）
            metric_docs.append(
                {
                    "metric_id": metric_id,
                    "name": metric_id,
                    "scope": SCOPE,
                    "status": STATUS_UNKNOWN,
                    "raw_value": None,
                    "normalized_value": None,
                    "unit": "N/A",
                    "threshold": dict(_NULL_THRESHOLD),
                    "evidence": {
                        "command": "",
                        "output_summary": None,
                        "raw_ref": f"raw/{metric_id}.out",
                        "sampled_at": collected_at,
                        **_normalized_replay_field(
                            mres["replay_command"]
                            if "replay_command" in mres
                            else _REPLAY_NOT_SUPPLIED
                        ),
                    },
                    "error": {
                        "code": ERROR_PARSE_FAILED,
                        "message": f"normalize 无该指标解析器: {metric_id}",
                        "metric_status": METRIC_ERROR_STATUS,
                    },
                    "provenance": {"config_sources": [], "doc_sources": [], "notes": None},
                }
            )
            continue
        error = mres.get("error")
        if error is not None:
            metric_docs.append(
                _error_metric_document(
                    metric_id,
                    error,
                    inspection_id=inspection_id,
                    collected_at=collected_at,
                    command=mres.get("command"),
                    replay_command=(
                        mres["replay_command"]
                        if "replay_command" in mres
                        else _REPLAY_NOT_SUPPLIED
                    ),
                )
            )
            continue
        try:
            parsed = PARSERS[metric_id](_parser_input(metric_id, mres))
        except ParseError as exc:
            metric_docs.append(
                _error_metric_document(
                    metric_id,
                    {
                        "code": ERROR_PARSE_FAILED,
                        "message": f"解析失败: {exc}",
                        "metric_status": METRIC_ERROR_STATUS,
                    },
                    inspection_id=inspection_id,
                    collected_at=collected_at,
                    command=mres.get("command"),
                    replay_command=(
                        mres["replay_command"]
                        if "replay_command" in mres
                        else _REPLAY_NOT_SUPPLIED
                    ),
                )
            )
            continue
        resolved = resolved_thresholds.get(metric_id)
        if resolved is None:
            metric_docs.append(
                _error_metric_document(
                    metric_id,
                    {
                        "code": ERROR_PARSE_FAILED,
                        "message": f"无阈值解析结果（无文档基线/外部配置）: {metric_id}",
                        "metric_status": METRIC_ERROR_STATUS,
                    },
                    inspection_id=inspection_id,
                    collected_at=collected_at,
                    command=mres.get("command"),
                    replay_command=(
                        mres["replay_command"]
                        if "replay_command" in mres
                        else _REPLAY_NOT_SUPPLIED
                    ),
                )
            )
            continue
        normalized = _normalized_value(metric_id, parsed)
        matched_rule = _apply_external_rules(metric_id, normalized, resolved)
        if matched_rule is not None:
            rule = matched_rule
            expr = (
                f"[{rule['range'][0]},{rule['range'][1]}]"
                if rule.get("range") is not None
                else f"{rule['op']}{rule['value']}"
            )
            config_sources = list(resolved.get("provenance", {}).get("config_sources", []))
            threshold = {
                "layer": LAYER_EXTERNAL_CONFIG,
                "rule_id": None,
                "value": expr,
                "source_anchor": config_sources[0] if config_sources else None,
                "notes": rule.get("note"),
            }
            evidence = {
                "command": mres.get("command") or _metric_definition(metric_id)["command"],
                "output_summary": mask_output(_output_summary(metric_id, parsed)),
                "raw_ref": f"raw/{metric_id}.out",
                "sampled_at": collected_at,
            }
            evidence.update(
                _normalized_replay_field(
                    mres["replay_command"]
                    if "replay_command" in mres
                    else _REPLAY_NOT_SUPPLIED
                )
            )
            details = _evidence_details(metric_id, parsed, resolved, profile)
            if details is not None:
                evidence["details"] = details
            metric_docs.append(
                _build_metric_document(
                    metric_id,
                    status=rule["status"],
                    raw_value=_raw_value(metric_id, parsed),
                    normalized_value=normalized,
                    threshold=threshold,
                    evidence=evidence,
                    error=None,
                    provenance={
                        "config_sources": config_sources,
                        "doc_sources": list(
                            resolved.get("provenance", {}).get("doc_sources", [])
                        ),
                        "notes": rule.get("note"),
                    },
                )
            )
            continue
        if resolved.get("layer") == LAYER_EXTERNAL_CONFIG:
            # 外部配置规则未命中（或指标非数值无法应用数值规则）→
            # 回退文档基线（HR §4 步骤 3），provenance 注记回退原因
            resolved = _fallback_to_baseline(resolved, metric_id)
        decision = JUDGERS[metric_id](parsed, resolved, profile)
        metric_docs.append(
            _judged_metric_document(
                metric_id,
                parsed,
                decision,
                resolved,
                inspection_id=inspection_id,
                collected_at=collected_at,
                profile=profile,
                command=mres.get("command"),
                    replay_command=(
                        mres["replay_command"]
                        if "replay_command" in mres
                        else _REPLAY_NOT_SUPPLIED
                    ),
            )
        )

    ok = sum(1 for m in metric_docs if m["status"] == STATUS_OK)
    warn = sum(1 for m in metric_docs if m["status"] == STATUS_WARN)
    crit = sum(1 for m in metric_docs if m["status"] == STATUS_CRIT)
    unknown = sum(1 for m in metric_docs if m["status"] == STATUS_UNKNOWN)
    executed = sum(1 for m in metric_docs if m["error"] is None)
    failed = len(metric_docs) - executed
    planned = int(host_result.get("summary", {}).get("total", len(metric_docs)))
    execution_status = host_result.get("execution_status", STATUS_SUCCESS)

    doc = {
        "schema": "host-result-v1",
        "schema_version": 1,
        "run_id": run_id,
        "inspection_id": inspection_id,
        "host": {
            "name": host_result.get("host", host_result.get("name", "")),
            "ip": mask_output(str(host_result.get("ip", ""))),
            "inventory_source": inventory_source,
            "product_profiles": product_profiles,
        },
        "collected_at": collected_at,
        "duration_sec": duration_sec,
        "execution_status": execution_status,
        "execution_summary": {
            "total_metrics": planned,
            "ok": ok,
            "warn": warn,
            "crit": crit,
            "unknown": unknown,
            "executed": executed,
            "failed": failed,
        },
        "metrics": metric_docs,
        "meta": dict(meta),
    }
    return _sweep_strings(doc)


def _fallback_to_baseline(resolved: Dict[str, Any], metric_id: str) -> Dict[str, Any]:
    """外部配置规则未命中 → 重建文档基线解析结果（HR §4 步骤 3 回退）。

    防御实现：直接重新加载文档基线（本切片基线文件为包内只读数据）。
    provenance 注记说明回退原因，并保留外部配置来源（config_sources）。
    """
    baseline = config_mod.build_resolved_thresholds()
    fallback = baseline.get(metric_id)
    if fallback is None:
        return resolved
    fallback = dict(fallback)
    provenance = dict(fallback.get("provenance", {}))
    provenance["config_sources"] = list(
        resolved.get("provenance", {}).get("config_sources", [])
    )
    provenance["notes"] = (
        "外部配置规则未命中，回退文档基线（HR §4 顺序）"
    )
    fallback["provenance"] = provenance
    return fallback


def normalize_run_results(
    run_result: Dict[str, Any],
    *,
    run_id: str,
    inspection_id: Optional[str] = None,
    collected_at: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    product_profiles: Optional[Sequence[str]] = None,
    resolved_thresholds: Optional[Dict[str, Dict[str, Any]]] = None,
    inventory_source: str = "local",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """运行级规范化（ansible_runner run() 结果 → 主机文档列表 + 主机错误）。

    返回：{"documents": [host-result-v1 …], "host_errors": {host: error|null},
           "execution_status": 运行级执行状态}。host_errors 供 fact_source
    汇总索引承载主机级 ERROR 明细（schema 无主机级 error 字段，见报告 D1）。
    """
    documents: List[Dict[str, Any]] = []
    host_errors: Dict[str, Any] = {}
    for host_result in run_result.get("hosts", []):
        # Per-host product profiles: hosts whose Nginx metrics survived the
        # process-discovery selection are Nginx nodes (HR §2 host.product_profiles).
        host_profiles = list(product_profiles or [])
        if any(
            str(m.get("metric_id", "")).startswith("local.nginx.")
            for m in host_result.get("metrics", [])
        ):
            if "nginx" not in host_profiles:
                host_profiles.append("nginx")
        if any(
            str(m.get("metric_id", "")).startswith("local.keepalived.")
            for m in host_result.get("metrics", [])
        ):
            if "keepalived" not in host_profiles:
                host_profiles.append("keepalived")
        if any(
            str(m.get("metric_id", "")).startswith("local.elasticsearch.")
            for m in host_result.get("metrics", [])
        ):
            if "elasticsearch" not in host_profiles:
                host_profiles.append("elasticsearch")
        documents.append(
            normalize_host_result(
                host_result,
                run_id=run_id,
                inspection_id=inspection_id,
                collected_at=collected_at,
                profile=profile,
                product_profiles=host_profiles,
                resolved_thresholds=resolved_thresholds,
                inventory_source=inventory_source,
                meta=meta,
            )
        )
        host_errors[host_result.get("host", host_result.get("name", ""))] = host_result.get("host_error")
    return {
        "documents": documents,
        "host_errors": host_errors,
        "execution_status": run_result.get("execution_status", STATUS_ERROR),
    }


# --------------------------------------------------------------------------
# 机器校验（host-result-v1.schema.json 语义子集；jsonschema 未安装替代）
# --------------------------------------------------------------------------

TOP_KEYS = {
    "schema", "schema_version", "run_id", "inspection_id", "host", "collected_at",
    "duration_sec", "execution_status", "execution_summary", "metrics", "meta",
}
HOST_KEYS = {"name", "ip", "inventory_source", "product_profiles"}
SUMMARY_KEYS = {"total_metrics", "ok", "warn", "crit", "unknown", "executed", "failed"}
META_KEYS = {
    "control_endpoint", "gather_facts", "serial", "become_scope", "generator",
    "generator_version",
}
METRIC_KEYS = {
    "metric_id", "name", "scope", "status", "raw_value", "normalized_value", "unit",
    "threshold", "evidence", "error", "provenance",
}
THRESHOLD_KEYS = {"layer", "rule_id", "value", "source_anchor", "notes"}
EVIDENCE_KEYS = {"command", "output_summary", "raw_ref", "sampled_at"}
EVIDENCE_OPTIONAL_KEYS = {"details", "replay_command"}
ERROR_KEYS = {"code", "message", "metric_status"}
PROVENANCE_KEYS = {"config_sources", "doc_sources", "notes"}

_META_CONSTS = {
    "control_endpoint": "Linux/WSL Python3",
    "gather_facts": False,
    "serial": 1,
    "become_scope": "minimal",
    "generator": "inspect.sh",
}

_INSPECTION_ID_RE = re.compile(r"^insp-[0-9]{14}-[A-Za-z0-9_.-]+$")
_COLLECTED_AT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T")
_METRIC_ID_RE = re.compile(r"^local\.")


class _V:
    """类型约束辅助（jsonschema type 语义子集）。"""

    @staticmethod
    def is_number(v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fail(source: str, message: str) -> None:
    raise ValueError(f"{source}: {message}")


def validate_host_result(doc: Any, source: str = "<host-result>") -> None:
    """按 host-result-v1.schema.json 语义校验文档（内嵌子集校验器）。

    校验：顶层/各嵌套对象键集与必填、字段类型、const/enum/pattern；
    与 inspect/schema/host-result-v1.schema.json 一致（该文件为机器真源，
    本函数为无 jsonschema 依赖时的等价语义实现）。违反 → ValueError。
    """
    if not isinstance(doc, dict):
        _fail(source, "顶层必须是对象")
    if set(doc) != TOP_KEYS:
        missing = TOP_KEYS - set(doc)
        extra = set(doc) - TOP_KEYS
        _fail(source, f"顶层键集不符（缺 {sorted(missing)}，多 {sorted(extra)}）")
    if doc["schema"] != "host-result-v1":
        _fail(source, "schema 必须为 host-result-v1")
    if doc["schema_version"] != 1:
        _fail(source, "schema_version 必须为 1")
    if not isinstance(doc["run_id"], str) or not doc["run_id"]:
        _fail(source, "run_id 必须为非空字符串")
    if not isinstance(doc["inspection_id"], str) or not _INSPECTION_ID_RE.fullmatch(
        doc["inspection_id"]
    ):
        _fail(source, f"inspection_id 不符合 ^insp-[0-9]{{14}}-…: {doc['inspection_id']!r}")
    if doc["execution_status"] not in (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_ERROR):
        _fail(source, f"execution_status 非法: {doc['execution_status']!r}")
    if not isinstance(doc["collected_at"], str) or not _COLLECTED_AT_RE.match(
        doc["collected_at"]
    ):
        _fail(source, f"collected_at 不符合 ^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T: {doc['collected_at']!r}")
    if not _V.is_number(doc["duration_sec"]) or doc["duration_sec"] < 0:
        _fail(source, "duration_sec 必须为非负数值")

    host = doc["host"]
    if not isinstance(host, dict):
        _fail(source, "host 必须是对象")
    if not HOST_KEYS.issubset(set(host)) or not set(host) <= HOST_KEYS:
        _fail(source, f"host 键集不符: {sorted(set(host) - HOST_KEYS)}")
    for key in ("name", "ip", "inventory_source"):
        if not isinstance(host.get(key), str) or not host[key]:
            _fail(source, f"host.{key} 必须为非空字符串")
    if "product_profiles" in host:
        if not isinstance(host["product_profiles"], list) or any(
            not isinstance(p, str) for p in host["product_profiles"]
        ):
            _fail(source, "host.product_profiles 必须为字符串数组")

    summary = doc["execution_summary"]
    if not isinstance(summary, dict) or set(summary) != SUMMARY_KEYS:
        _fail(source, "execution_summary 键集不符")
    for key in SUMMARY_KEYS:
        if not isinstance(summary[key], int) or isinstance(summary[key], bool) or summary[key] < 0:
            _fail(source, f"execution_summary.{key} 必须为非负整数")

    meta = doc["meta"]
    if not isinstance(meta, dict) or set(meta) != META_KEYS:
        _fail(source, "meta 键集不符")
    for key, expected in _META_CONSTS.items():
        if meta.get(key) != expected:
            _fail(source, f"meta.{key} 必须为 {expected!r}")
    if not isinstance(meta["generator_version"], str) or not meta["generator_version"]:
        _fail(source, "meta.generator_version 必须为非空字符串")

    if not isinstance(doc["metrics"], list):
        _fail(source, "metrics 必须是数组")
    for i, metric in enumerate(doc["metrics"]):
        _validate_metric(metric, f"{source}.metrics[{i}]")


def _validate_metric(metric: Any, where: str) -> None:
    if not isinstance(metric, dict):
        _fail(where, "metric 必须是对象")
    if set(metric) != METRIC_KEYS:
        _fail(where, f"metric 键集不符: {sorted(set(metric) - METRIC_KEYS)}")
    if not isinstance(metric["metric_id"], str) or not _METRIC_ID_RE.match(metric["metric_id"]):
        _fail(where, f"metric_id 不符合 ^local\\.: {metric['metric_id']!r}")
    for key in ("name", "scope", "unit"):
        if not isinstance(metric[key], str) or not metric[key]:
            _fail(where, f"{key} 必须为非空字符串")
    if metric["status"] not in STATUSES:
        _fail(where, f"status 非法（四状态）: {metric['status']!r}")
    if metric["raw_value"] is not None and not isinstance(
        metric["raw_value"], (str, int, float, bool)
    ):
        _fail(where, "raw_value 类型非法")
    nv = metric["normalized_value"]
    if nv is not None and not _V.is_number(nv):
        _fail(where, "normalized_value 必须为数值或 null")
    if metric["error"] is not None:
        err = metric["error"]
        if not isinstance(err, dict) or set(err) != ERROR_KEYS:
            _fail(where, "error 键集不符")
        if err["code"] not in ERROR_CODES:
            _fail(where, f"error.code 非法: {err['code']!r}")
        if not isinstance(err["message"], str):
            _fail(where, "error.message 必须为字符串")
        if err["metric_status"] != METRIC_ERROR_STATUS:
            _fail(where, "error.metric_status 必须为 UNKNOWN")
        if metric["status"] != STATUS_UNKNOWN:
            _fail(where, "error 存在时 status 必须为 UNKNOWN（执行/业务分离）")
    _validate_threshold(metric["threshold"], f"{where}.threshold")
    _validate_evidence(metric["evidence"], f"{where}.evidence")
    _validate_provenance(metric["provenance"], f"{where}.provenance")


def _validate_threshold(threshold: Any, where: str) -> None:
    if not isinstance(threshold, dict) or set(threshold) != THRESHOLD_KEYS:
        _fail(where, "threshold 键集不符")
    layer = threshold["layer"]
    if layer not in (
        LAYER_DOCUMENT_BASELINE,
        LAYER_EXTERNAL_CONFIG,
        LAYER_UNRESOLVED,
        None,
    ):
        _fail(where, f"threshold.layer 非法: {layer!r}")
    for key in ("rule_id", "value", "source_anchor", "notes"):
        if threshold[key] is not None and not isinstance(
            threshold[key], (str, int, float)
        ):
            _fail(where, f"threshold.{key} 类型非法")


def _validate_evidence(evidence: Any, where: str) -> None:
    if not isinstance(evidence, dict):
        _fail(where, "evidence 必须为对象")
    keys = set(evidence)
    if not EVIDENCE_KEYS.issubset(keys) or keys - EVIDENCE_KEYS - EVIDENCE_OPTIONAL_KEYS:
        _fail(where, "evidence 键集不符")
    if not isinstance(evidence["command"], str):
        _fail(where, "evidence.command 必须为字符串")
    if "replay_command" in evidence:
        try:
            validate_replay_command(evidence["replay_command"])
        except ReplayCommandError as exc:
            _fail(where, str(exc))
    for key in ("output_summary", "raw_ref", "sampled_at"):
        if evidence[key] is not None and not isinstance(evidence[key], str):
            _fail(where, f"evidence.{key} 必须为字符串或 null")
    if "details" in evidence:
        details = evidence["details"]
        if not isinstance(details, list):
            _fail(where, "evidence.details 必须为数组")
        for index, detail in enumerate(details):
            detail_where = f"{where}.details[{index}]"
            if not isinstance(detail, dict):
                _fail(detail_where, "证据明细必须为对象")
            detail_keys = set(detail)
            if {"window", "load", "cpu_cores", "status", "judgement"}.issubset(detail_keys):
                required_detail_keys = {"window", "load", "cpu_cores", "status", "judgement"}
                if detail_keys != required_detail_keys:
                    _fail(detail_where, "系统负载明细键集不符")
                if not isinstance(detail["window"], str) or not detail["window"]:
                    _fail(detail_where, "window 必须为非空字符串")
                load = detail["load"]
                if isinstance(load, bool) or not isinstance(load, (int, float)) or load < 0:
                    _fail(detail_where, "load 必须为非负数值")
                cores = detail["cpu_cores"]
                if cores is not None and (isinstance(cores, bool) or not isinstance(cores, int) or cores < 1):
                    _fail(detail_where, "cpu_cores 必须为正整数或 null")
                if detail["status"] not in STATUSES:
                    _fail(detail_where, "status 必须为 OK/WARN/CRIT/UNKNOWN")
                if not isinstance(detail["judgement"], str) or not detail["judgement"]:
                    _fail(detail_where, "judgement 必须为非空字符串")
                continue
            required_detail_keys = {"filesystem", "mount", "used_percent"}
            if not required_detail_keys.issubset(detail_keys) or detail_keys - required_detail_keys - {"status"}:
                _fail(detail_where, "证据明细键集不符")
            if not isinstance(detail["filesystem"], str) or not detail["filesystem"]:
                _fail(detail_where, "filesystem 必须为非空字符串")
            if not isinstance(detail["mount"], str) or not detail["mount"]:
                _fail(detail_where, "mount 必须为非空字符串")
            used = detail["used_percent"]
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
                _fail(detail_where, "used_percent 必须为 0..100 数值")
            if "status" in detail and detail["status"] not in STATUSES:
                _fail(detail_where, "status 必须为 OK/WARN/CRIT/UNKNOWN")


def _validate_provenance(provenance: Any, where: str) -> None:
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
        _fail(where, "provenance 键集不符")
    for key in ("config_sources", "doc_sources"):
        if not isinstance(provenance[key], list) or any(
            not isinstance(s, str) for s in provenance[key]
        ):
            _fail(where, f"provenance.{key} 必须为字符串数组")
    if provenance["notes"] is not None and not isinstance(provenance["notes"], str):
        _fail(where, "provenance.notes 必须为字符串或 null")


__all__ = [
    "ERROR_CODES",
    "ERROR_COMMAND_NOT_FOUND",
    "ERROR_CONNECTION_FAILED",
    "ERROR_DATA_MISSING",
    "ERROR_PARSE_FAILED",
    "ERROR_PERMISSION_DENIED",
    "ERROR_PROBE_FAILED",
    "ERROR_TIMEOUT",
    "ERROR_UNSUPPORTED_PROFILE",
    "JUDGERS",
    "LAYER_DOCUMENT_BASELINE",
    "LAYER_EXTERNAL_CONFIG",
    "LAYER_UNRESOLVED",
    "MASKED_CRED",
    "MASKED_IP",
    "METRIC_ERROR_STATUS",
    "NUMERIC_METRIC_IDS",
    "PARSERS",
    "PARSER_NAMES",
    "SCOPE",
    "STATUS_CRIT",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_SUCCESS",
    "STATUS_UNKNOWN",
    "STATUSES",
    "ParseError",
    "contains_credential",
    "contains_plain_ip",
    "make_inspection_id",
    "mask_credentials",
    "mask_ip",
    "mask_output",
    "normalize_host_result",
    "normalize_replay_command",
    "normalize_run_results",
    "parse_cpu_load_1m",
    "parse_cpu_utilization",
    "parse_filesystem_inode_used_percent",
    "parse_filesystem_used_percent",
    "parse_logs_key_evidence",
    "parse_memory_available_percent",
    "parse_port_listening",
    "parse_nginx_access_log_status_codes",
    "parse_nginx_config_baseline",
    "parse_nginx_config_valid",
    "parse_nginx_connections_status",
    "parse_nginx_error_log",
    "parse_nginx_port_listening",
    "parse_nginx_http_reachability",
    "parse_nginx_stub_status_connections",
    "parse_nginx_proxy_upstream_config",
    "parse_nginx_fd_process_limits",
    "parse_nginx_https_certificate",
    "parse_nginx_security_baseline",
    "parse_nginx_version",
    "parse_keepalived_capability_stability",
    "parse_keepalived_config_baseline",
    "parse_keepalived_error_log",
    "parse_keepalived_healthcheck",
    "parse_keepalived_version",
    "parse_keepalived_vip_access",
    "parse_keepalived_vip_bound",
    "parse_elasticsearch_certificate",
    "parse_elasticsearch_cluster_health",
    "parse_elasticsearch_cluster_settings",
    "parse_elasticsearch_discovery_config",
    "parse_elasticsearch_heap_gc",
    "parse_elasticsearch_indices",
    "parse_elasticsearch_nodes",
    "parse_elasticsearch_nodes_cpu",
    "parse_elasticsearch_nodes_disk",
    "parse_elasticsearch_nodes_memory",
    "parse_elasticsearch_security",
    "parse_elasticsearch_service_port",
    "parse_elasticsearch_shards",
    "parse_elasticsearch_slowlog",
    "parse_elasticsearch_snapshot",
    "parse_elasticsearch_system_parameters",
    "parse_elasticsearch_thread_pool",
    "parse_elasticsearch_version",
    "parse_elasticsearch_watermark",
    "parse_process_present",
    "parse_service_active",
    "parse_swap_used_percent",
    "validate_host_result",
]
