"""inspect/ansible_runner.py — playbook 生成、执行封装与结果回传（T-103）。

职责（docs/specs/technical-design.md §4 ansible_runner.py 行 + AE §1-§7）：
  - playbook 生成：gather_facts:false、serial:1、raw 模块 + `/bin/bash -lc`
    只读命令、最小化 become（仅声明需特权的单条命令）、每命令超时注入
    （probe 15s / 指标 10s / 日志 15s）、无重试（AE §7）；
  - 只读命令 allow-list（AE §4.1）：可执行命令集合唯一来自指标定义
    （metrics.py + TD §5.2 数据源列转写注册表），未登记命令一律拒绝；
  - 执行封装：prepare_run 生成 playbook 与 ansible-playbook argv
    （build_playbook_argv，不含任何凭据），execute_plan 执行并分类回传
    （连接失败→ERROR 无业务结论；部分失败→PARTIAL，AE §6）；
  - INSPECT_FIXTURE_DIR 调试注入点（TD §10.2 / REQ-N-08）：指向预录
    输出目录时返回夹具输出、不产生任何连接，且 stderr 声明“调试模式
    （fixture）”；夹具文件首行 `#` 注释为“非实测数据”标注（RK-R2-06），
    读取时剥离；
  - 单主机总时长上限 300s（AE §7）：fixture 为默认零真实执行路径；G0 真实路径
    仅在 WSL/Linux、显式门控、明确授权目标与结构化 callback 条件同时满足时执行。
    真实路径失败不伪造业务结论。

模块边界（TD §4）：本模块单向依赖 inspect.probe（能力矩阵）与
inspect.metrics（指标定义）；不导入 inspect.inventory（主机选择由
cli 编排，本模块以鸭子类型消费 HostSelection）；禁止非 allow-list
命令、become 滥用、重试（TD §4 禁止行为列）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from inspect import metrics as metrics_registry
from inspect import probe as probe_mod
from inspect.modules import default_registry

try:
    from inspect import runtime as runtime_contract
except ImportError:  # stdlib inspect is not a package in isolated unit tests.
    _runtime_spec = importlib.util.spec_from_file_location(
        "inspect.runtime", Path(__file__).with_name("runtime.py")
    )
    runtime_contract = importlib.util.module_from_spec(_runtime_spec)
    sys.modules["inspect.runtime"] = runtime_contract
    assert _runtime_spec.loader is not None
    _runtime_spec.loader.exec_module(runtime_contract)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# fixture 调试模式环境变量（TD §10.2，REQ-N-08；显式开启 + stderr 声明）
FIXTURE_ENV_VAR = "INSPECT_FIXTURE_DIR"

# 真实执行必须显式开启；默认保持安全失败。账号和 ask-pass 选项只控制
# Ansible 原生 transport，不接受密码值，避免凭据进入 argv/结果。
REAL_EXEC_ENV_VAR = "INSPECT_ENABLE_REAL"
REMOTE_USER_ENV_VAR = "INSPECT_REMOTE_USER"
ASK_PASS_ENV_VAR = "INSPECT_ASK_PASS"
LOCAL_REAL_ENV_VAR = "INSPECT_ENABLE_LOCAL_REAL"
REAL_EXEC_ENABLED = "1"

# 结构化 stdout callback 与本地重试文件关闭，避免把不可解析的默认文本当事实源。
ANSIBLE_STDOUT_CALLBACK = "json"
REAL_PROCESS_TIMEOUT_GRACE_SEC = 30
MAX_CAPTURED_ERROR_CHARS = 1200

# G0 真实路径的目标范围：只允许本次明确授权的两台 VM；本机/其他地址
# 仍可通过 fixture 或后续另行批准的执行合同使用，但不能借此真实连接。
REAL_ALLOWED_TARGETS = frozenset({"192.168.0.10", "192.168.0.101"})

# 超时（AE §7 / TD §5.1-5.2）：probe 15s；指标 10s（日志类 15s）；
# 单主机总时长上限 300s
PROBE_TIMEOUT_SEC = probe_mod.PROBE_TIMEOUT_SEC
METRIC_TIMEOUT_SEC = 10
LOG_METRIC_TIMEOUT_SEC = 15
HOST_TIMEOUT_SEC = 300

# GNU coreutils timeout 的默认退出码（命令超时 → 分类为 TIMEOUT）
TIMEOUT_RC = 124

# host-result-v1 error.code 枚举（HR §1.4 / TD §4 error 枚举；T-104 消费）
ERROR_CONNECTION_FAILED = "CONNECTION_FAILED"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_PERMISSION_DENIED = "PERMISSION_DENIED"
ERROR_COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
ERROR_DATA_MISSING = "DATA_MISSING"
ERROR_PROBE_FAILED = "PROBE_FAILED"
ERROR_UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
ERROR_CODES = (
    ERROR_CONNECTION_FAILED,
    ERROR_TIMEOUT,
    ERROR_PERMISSION_DENIED,
    ERROR_COMMAND_NOT_FOUND,
    ERROR_DATA_MISSING,
    ERROR_PROBE_FAILED,
    ERROR_UNSUPPORTED_PROFILE,
)

# error.metric_status（HR §1.4：技术失败一律 UNKNOWN，不伪装业务 CRIT）
METRIC_ERROR_STATUS = "UNKNOWN"

# execution_status（HR §1.2 / AE §6）
STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_ERROR = "ERROR"

# stderr 权限失败特征（→ PERMISSION_DENIED；AE §5：单指标权限不足→UNKNOWN+继续）
_PERMISSION_PATTERNS = (
    "permission denied",
    "operation not permitted",
    "sudo:",
    "not authorized",
    "no permission",
)

# profile 取值安全字符集（注入防护，RK-R3-03：禁止 shell 拼接自由参数；
# 值属配置边界，仅允许安全字符，杜绝 `$()'";&|` 等逃逸）
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_./:@%+,\- ]+$")
_SAFE_UNIT = re.compile(r"^[A-Za-z0-9_@.\-]+$")
_SAFE_PATH = re.compile(r"^/([A-Za-z0-9_./@:+\-*?]*)$")

# 默认运行期目录（<仓库根>/.runtime，TD §3；与 inventory.py 同名约定，
# 不导入 inventory 以保持 TD §4 依赖方向：ansible_runner → probe/metrics）
_RUNTIME_DIR_NAME = ".runtime"

# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------


class CommandNotAllowedError(Exception):
    """allow-list 拒绝（AE §4.1）：未登记指标/未登记命令/越权参数。

    属执行失败（cli-contract §4 退出码 10）。
    """

    exit_code = 10


class CommandConfigError(Exception):
    """命令构造错误（profile 值非法/注册表不一致）。

    属执行失败（cli-contract §4 退出码 10）。
    """

    exit_code = 10


class ExecutionNotReadyError(Exception):
    """真实 ansible-playbook 执行未启用（G0 预检前置，AE §8）。

    控制端未就绪属执行失败（cli-contract §4 退出码 10，无业务结论）；
    本任务全部行为经 INSPECT_FIXTURE_DIR fixture 模式验证。
    """

    exit_code = 10


class RealExecutionError(Exception):
    """Real Ansible execution or callback failure (exit code 10)."""

    exit_code = 10

    def __init__(
        self,
        message: str,
        *,
        category: str = "real_execution_failed",
        check: str = "inspect sanitized diagnostics",
        return_code: Optional[int] = None,
    ) -> None:
        self.category = category
        self.return_code = return_code
        self.check = check
        self.cleanup_diagnostic: Optional[Dict[str, Any]] = None
        suffix = f"; category={category}; check={check}"
        if return_code is not None:
            suffix += f"; return_code={return_code}"
        super().__init__(message + suffix)


class FixtureError(Exception):
    """fixture 模式配置错误（夹具目录不存在等）。退出码 10。"""

    exit_code = 10


# --------------------------------------------------------------------------
# 命令注册表（allow-list 唯一来源：AE §4.1 / TD §5.2 数据源列只读转写）
# --------------------------------------------------------------------------


@dataclass
class CommandSpec:
    """单条指标采集命令规格（allow-list 校验后进入 playbook）。

    command=None 表示因无 profile 配置未构造命令（error_code=
    UNSUPPORTED_PROFILE，MR §5：无 profile → UNKNOWN，不静默跳过）。
    """

    metric_id: str
    command: Optional[str]
    timeout_sec: int
    become: bool
    required_commands: Tuple[str, ...]
    source_anchor: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# 每指标：命令模板（TD §5.2 数据源列逐字转写，{…} 为 profile 占位）、
# 超时（metrics.py timeout_sec）、become（MR §5 unknown_conditions 中
# "无权限→UNKNOWN" 的指标才声明最小化 become，AE §5）、所需命令（probe.py）。
# 注：local.logs.key_evidence 模板按 TD §5.2 用 `egrep`；探测集合（TD §5.1）
# 仅含 `grep`（egrep 为 grep 家族，G0 预检项），required_commands 记 grep。
_COMMAND_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "local.process.present": {
        "command": "pgrep -fa '{process_pattern}' || ps -ef | grep '{grep_pattern}'",
        "profile_keys": ("process_pattern",),
        "become": False,
        "anchor": "MR §5.1 服务/进程行（9 份巡检手册）+ TD §5.2 local.process.present",
    },    "local.service.active": {
        "command": "systemctl is-active {unit}; systemctl show -p ActiveState,SubState {unit}",
        "profile_keys": ("unit",),
        "become": False,
        "anchor": "MR §5.2 systemd 服务行 + 部署规范 systemd 章节 + TD §5.2 local.service.active",
    },
    "local.port.listening": {
        "command": "ss -tlnp | grep -E ':{ports}'",
        "profile_keys": ("ports",),
        "become": True,  # ss -p 需特权核对监听进程名（MR：ss 权限不足→UNKNOWN）
        "anchor": "MR §5.3 端口行 + TD §5.2 local.port.listening",
    },
    "local.cpu.utilization": {
        "command": "top -bn2 -d 1 | grep 'Cpu(s)' | tail -1; ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -10",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.4 CPU 行 + TD §5.2 local.cpu.utilization",
    },
    "local.cpu.load_1m": {
        "command": "cat /proc/loadavg; nproc",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.4 CPU 行 + TD §5.2 local.cpu.load_1m",
    },
    "local.memory.available_percent": {
        "command": "free -m",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.5 内存行 + TD §5.2 local.memory.available_percent",
    },
    "local.swap.used_percent": {
        "command": "free -m",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.5 内存行 + TD §5.2 local.swap.used_percent",
    },
    "local.filesystem.used_percent": {
        "command": "df -hT /",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.6 磁盘行 + TD §5.2 local.filesystem.used_percent",
    },
    "local.filesystem.inode_used_percent": {
        "command": "df -i /",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.6 磁盘行 + TD §5.2 local.filesystem.inode_used_percent",
    },
    "local.logs.key_evidence": {
        "command": "tail -300 {log_paths} | egrep -i '{log_keywords}'",
        "profile_keys": ("log_paths", "log_keywords"),
        "become": True,  # 读取其他用户日志（AE §5 最小化 become 原文示例）
        "anchor": "MR §5.10 关键日志行 + TD §5.2 local.logs.key_evidence",
    },
}

# 日志类指标（超时 15s，AE §7 / TD §5.2 超时列）
_LOG_METRIC_IDS = {"local.logs.key_evidence"}


# --------------------------------------------------------------------------
# profile 安全校验与命令构造（注入防护，RK-R3-03）
# --------------------------------------------------------------------------


def _validate_profile_value(key: str, value: Any) -> str:
    """校验并归一化单个 profile 值（安全字符集，杜绝 shell 逃逸）。

    process_pattern / log_keywords：非空字符串，安全字符集；
    unit：非空字符串（服务名单字符集）；
    ports：1..65535 整数列表 → `9200|9300` 形式；
    fs_paths / log_paths：绝对路径列表（log_paths 允许 glob `*` `?`）。

    非法值 → CommandConfigError（退出码 10，配置边界错误按执行失败）。
    """
    if key == "ports":
        if not isinstance(value, list) or not value:
            raise CommandConfigError(f"profile ports 必须为非空整数列表: {value!r}")
        nums: List[str] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise CommandConfigError(f"profile ports 元素必须为整数: {item!r}")
            if not 1 <= item <= 65535:
                raise CommandConfigError(f"profile ports 超出 1..65535: {item!r}")
            nums.append(str(item))
        # 分组括号：grep -E ':(9200|9300)'（每个端口都需前导冒号锚定）
        return "(" + "|".join(nums) + ")"
    if key in ("fs_paths", "log_paths"):
        if not isinstance(value, list) or not value:
            raise CommandConfigError(f"profile {key} 必须为非空路径列表: {value!r}")
        paths: List[str] = []
        for p in value:
            if not isinstance(p, str) or not _SAFE_PATH.fullmatch(p):
                raise CommandConfigError(
                    f"profile {key} 路径非法（需绝对路径，仅限安全字符）: {p!r}"
                )
            paths.append(p)
        return " ".join(paths)
    if key == "unit":
        if not isinstance(value, str) or not _SAFE_UNIT.fullmatch(value):
            raise CommandConfigError(f"profile unit 非法: {value!r}")
        return value
    # process_pattern / log_keywords
    if isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, str) or not _SAFE_WORD.fullmatch(item) or not item:
                raise CommandConfigError(f"profile {key} 元素非法: {item!r}")
            parts.append(item)
        return "|".join(parts)
    if not isinstance(value, str) or not _SAFE_WORD.fullmatch(value) or not value:
        raise CommandConfigError(f"profile {key} 非法: {value!r}")
    return value


def _grep_self_exclusion_pattern(pattern: str) -> str:
    """`grep '[x]xx'` 自排除技巧（TD §5.2：`grep '[p]attern'`，防 grep 自匹配）。"""
    return f"[{pattern[0]}]{pattern[1:]}" if pattern else pattern


def _substitute_template(
    template: str, profile_keys: Tuple[str, ...], profile: Dict[str, Any]
) -> str:
    """用已校验 profile 值替换模板占位符（{key}）。

    派生占位符：`{grep_pattern}` = process_pattern 的自排除写法
    （TD §5.2 `grep '[p]attern'` 防 grep 自匹配）；pgrep -fa 用原文。
    """
    values: Dict[str, str] = {}
    for key in profile_keys:
        values[key] = _validate_profile_value(key, profile.get(key))
    if "{grep_pattern}" in template:
        if "process_pattern" not in values:
            raise CommandConfigError(
                f"注册表模板依赖派生占位符但缺 process_pattern: {template!r}"
            )
        values["grep_pattern"] = _grep_self_exclusion_pattern(
            values["process_pattern"]
        )
    out = template
    for key, value in values.items():
        placeholder = "{" + key + "}"
        if placeholder not in out:
            raise CommandConfigError(f"注册表模板缺少占位符 {placeholder}: {template!r}")
        out = out.replace(placeholder, value)
    return out


def build_metric_command_specs(
    metrics: Optional[Sequence[Dict[str, Any]]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> List[CommandSpec]:
    """由指标注册表（metrics.py）+ TD §5.2 模板构造采集命令规格列表。

    - metrics=None → 全部 10 个已实现指标（metrics_registry.iter_metrics()）；
    - profile：inspect.yml profiles 中单个产品的配置（TD §6.3）：
      提供 → 安全校验后替换占位符；缺失/未提供 → 需要 profile 的指标
      构造 command=None + error_code=UNSUPPORTED_PROFILE（MR §5：无
      profile 配置 → 指标 UNKNOWN，不静默跳过）；linux_basic 的基础
      指标（CPU/负载/内存/Swap/根文件系统）始终构造命令。
    - 超时取自 metrics.py 定义（timeout_sec：10s，日志类 15s，AE §7）；
    - 所需命令取自 probe.metric_required_commands（TD §5.2 数据源列）。
    """
    if metrics is None:
        metrics = default_registry().metric_definitions()
    profile = profile or {}
    specs: List[CommandSpec] = []
    for m in metrics:
        metric_id = m["metric_id"]
        entry = _COMMAND_TEMPLATES.get(metric_id)
        if entry is None:
            raise CommandConfigError(
                f"allow-list 注册表缺少指标定义: {metric_id}（AE §4.1 唯一来源）"
            )
        timeout_sec = m.get("timeout_sec")
        if timeout_sec not in (METRIC_TIMEOUT_SEC, LOG_METRIC_TIMEOUT_SEC):
            raise CommandConfigError(
                f"指标超时越界（允许 {METRIC_TIMEOUT_SEC}/{LOG_METRIC_TIMEOUT_SEC}s）: "
                f"{metric_id}={timeout_sec!r}"
            )
        required = probe_mod.metric_required_commands(metric_id)
        if not required:
            raise CommandConfigError(f"指标所需命令映射缺失: {metric_id}")
        if all(profile.get(k) is not None for k in entry["profile_keys"]):
            command = _substitute_template(
                entry["command"], entry["profile_keys"], profile
            )
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                )
            )
        else:
            missing = [k for k in entry["profile_keys"] if profile.get(k) is None]
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=None,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    error_code=ERROR_UNSUPPORTED_PROFILE,
                    error_message=(
                        f"无 profile 配置（缺 {', '.join(missing)}）；"
                        f"MR §5：无 profile → UNKNOWN"
                    ),
                )
            )
    return specs


# --------------------------------------------------------------------------
# allow-list 校验（AE §4.1：命令唯一来自指标定义；未登记命令拒绝）
# --------------------------------------------------------------------------


# 仅用于校验的可执行名提取：shell 关键字 / 数值（timeout N 前缀）/
# 重定向符为段前缀，跳过；未命中关键字/数值/重定向的段首 token 即
# 可执行名（引号内字符视为参数，不参与分隔符切分）。
_SHELL_KEYWORDS = {
    "if", "then", "else", "elif", "fi", "for", "while", "until",
    "do", "done", "case", "esac", "function", "in", "!", "timeout",
}
_REDIRECT_RE = re.compile(r"(?:1|2)?>>?|<<<|<|>")


def _tokenize(command: str) -> List[Optional[str]]:
    """迷你 shell 词法切分：引号内整体为一个词（`'…'`/`"…"`），
    `; | & ( )` 为段分隔符（None 标记），空白/换行分隔普通词。

    `$`/反引号按普通词字符处理（非分隔符），保证扫描每次至少前进
    一个字符——裸 `$`/反引号（如 `free -m $`、`$(rm -rf /)`、
    `` `whoami` ``）不会再死循环（T-103F H-1 修复）；含命令替换/
    变量展开指示符的注入一律拒绝由 parse_binaries 判定（见该函数）。
    """
    tokens: List[Optional[str]] = []
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in ";|&()":
            tokens.append(None)
            i += 1
        elif c in "'\"":
            j = command.find(c, i + 1)
            if j == -1:
                j = n
            tokens.append(command[i : j + 1])
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not command[j].isspace() and command[j] not in ";|&()'\"":
                j += 1
            tokens.append(command[i:j])
            i = j
    return tokens


def parse_binaries(command: str) -> List[str]:
    """提取命令中的可执行名（allow-list 校验用；仅校验，不做任何执行）。

    规则：按段分隔符（`;`/`|`/`&&`/`||`/`(`/`)`）切分，取每段首个
    非跳过 token（引号内的 `|` 等为参数内容，不切分）；段前缀跳过：
    shell 关键字、数值（`timeout N` 包装前缀）、重定向符。引号
    （`'…'`/`"…"`）不影响可执行名判定（`'rm' -rf /` 仍提取 rm）。

    注入一律拒绝（T-103F H-1/H-2 修复）：任一 token 含 `$` 或反引号
    （命令替换 `$()`/反引号、变量展开 `$VAR`——含双引号内整体成词的
    情况，shell 在引号内同样展开）即抛 CommandNotAllowedError；allow
    list 注册表模板经 profile 安全字符集校验后不可能出现这两个字符，
    因此一律拒绝而非跳过（AE §4.1 / RK-R3-03）。
    """
    binaries: List[str] = []
    first_in_segment = True
    for word in _tokenize(command):
        if word is None:
            first_in_segment = True
            continue
        if "$" in word or "`" in word:
            raise CommandNotAllowedError(
                "allow-list 拒绝：命令含命令替换/变量展开指示符"
                "（`$`/反引号），引号内亦会被 shell 展开，注入一律拒绝"
                f"（AE §4.1 / RK-R3-03）: {command!r}"
            )
        if not first_in_segment:
            continue
        bare = word.strip("\"'")
        if not bare or bare in _SHELL_KEYWORDS or re.fullmatch(r"\d+", bare):
            continue
        if _REDIRECT_RE.fullmatch(bare):
            continue
        binaries.append(bare)
        first_in_segment = False
    return binaries


def _allowed_binaries(metric_id: str) -> List[str]:
    """指标允许的可执行名 = 注册表模板自身的可执行名（AE §4.1 唯一来源）。"""
    entry = _COMMAND_TEMPLATES[metric_id]
    return parse_binaries(entry["command"])


def validate_command_specs(specs: Sequence[CommandSpec]) -> None:
    """allow-list 校验（AE §4.1 / RK-R3-03）：拒绝未登记命令/越权参数。

    拒绝条件（任一即 CommandNotAllowedError，退出码 10）：
      - 未登记指标（注册表外 metric_id）；
      - 命令可执行名超出该指标注册表模板的可执行名集合（含注入尝试）；
      - 命令含命令替换/变量展开指示符（`$`/反引号，含引号内）——
        parse_binaries 抛错，注入一律拒绝（T-103F H-1/H-2）；
      - 超时不在允许集（10/15s，AE §7）；
      - become 与注册表声明不一致（最小化 become 边界，AE §5）；
      - command=None 但 error_code 非 UNSUPPORTED_PROFILE。
    """
    for spec in specs:
        entry = _COMMAND_TEMPLATES.get(spec.metric_id)
        if entry is None:
            raise CommandNotAllowedError(
                f"allow-list 拒绝：指标未登记: {spec.metric_id!r}"
            )
        if spec.timeout_sec not in (METRIC_TIMEOUT_SEC, LOG_METRIC_TIMEOUT_SEC):
            raise CommandNotAllowedError(
                f"allow-list 拒绝：超时越界（10/15s）: {spec.metric_id}={spec.timeout_sec}"
            )
        if bool(spec.become) != bool(entry["become"]):
            raise CommandNotAllowedError(
                f"allow-list 拒绝：become 与注册表声明不一致（最小化 become）: "
                f"{spec.metric_id}={spec.become!r}"
            )
        if spec.command is None:
            if spec.error_code != ERROR_UNSUPPORTED_PROFILE:
                raise CommandNotAllowedError(
                    f"allow-list 拒绝：命令缺失且非 UNSUPPORTED_PROFILE: {spec.metric_id}"
                )
            continue
        allowed = _allowed_binaries(spec.metric_id)
        found = parse_binaries(spec.command)
        if not found:
            raise CommandNotAllowedError(
                f"allow-list 拒绝：无法识别命令: {spec.command!r}"
            )
        offenders = [b for b in found if b not in allowed]
        if offenders:
            raise CommandNotAllowedError(
                f"allow-list 拒绝：命令可执行名不在指标 {spec.metric_id} "
                f"允许集合内: {offenders}（允许: {allowed}）"
            )


# --------------------------------------------------------------------------
# playbook 生成（AE §1-§7 文本契约）
# --------------------------------------------------------------------------


def _sh_escape(value: str) -> str:
    """单引号转义（`'` → `'\\''`），用于嵌入 `/bin/bash -lc '…'`。"""
    return value.replace("'", "'\\''")


def _yaml_single_quote(value: str) -> str:
    """YAML 单引号标量转义（`'` → `''`；单引号标量中反斜杠为字面量）。"""
    return value.replace("'", "''")


def generate_playbook(
    specs: Sequence[CommandSpec],
    probe_command: Optional[str] = None,
) -> str:
    """生成采集 playbook 文本（YAML）。

    契约（AE §1-§7 文本断言）：
      - play 级：hosts: all、gather_facts: false、serial: 1；
      - 每任务：ansible.builtin.raw + `timeout N /bin/bash -lc '…'`
        （N=15 探测 / 10 指标 / 15 日志，AE §7 超时注入）；
      - become：仅注册表声明需要特权的单条命令 become: true（AE §5
        最小化 become），其余 false；
      - 无 retries/until（AE §7：超时/连接失败不自动重试）；
      - 忽略单命令失败（rc 语义留给 normalize，T-104）：ignore_errors。
    """
    probe_command = probe_command or probe_mod.build_probe_command()
    lines = [
        "---",
        "# inspect 采集 playbook（T-103 ansible_runner 生成；ansible-execution v1）",
        "# 契约：gather_facts:false / serial:1 / raw + /bin/bash -lc / 最小化 become /",
        "#       只读命令 allow-list / 每命令超时注入（probe 15s、指标 10s、日志 15s、",
        "#       单主机 300s）/ 无重试（AE §1-§7；超时与连接失败不自动重试）",
        '- name: "inspect collection"',
        "  hosts: all",
        "  gather_facts: false",
        "  serial: 1",
        "  tasks:",
    ]
    lines.append(f'    - name: "probe: 能力探测（{PROBE_TIMEOUT_SEC}s）"')
    lines.append(
        f"      ansible.builtin.raw: '{_yaml_single_quote(probe_command)}'"
    )
    lines.append("      become: false")
    lines.append("      register: inspect_probe")
    lines.append("      ignore_errors: true")
    for idx, spec in enumerate(specs):
        if spec.command is None:
            continue  # UNSUPPORTED_PROFILE：不进 playbook（无命令可执行）
        raw_cmd = f"timeout {spec.timeout_sec} /bin/bash -lc '{_sh_escape(spec.command)}'"
        lines.append(
            f'    - name: "metric: {spec.metric_id}（{spec.timeout_sec}s）"'
        )
        lines.append(
            f"      ansible.builtin.raw: '{_yaml_single_quote(raw_cmd)}'"
        )
        lines.append(f"      become: {str(spec.become).lower()}")
        lines.append(f"      register: inspect_metric_{idx}")
        lines.append("      ignore_errors: true")
    lines.append("")
    return "\n".join(lines)


def build_playbook_argv(
    playbook_path: Path,
    inventory_path: Path,
    limit: Optional[str] = None,
    *,
    remote_user: Optional[str] = None,
    ask_pass: bool = False,
    executable: Optional[str] = None,
) -> List[str]:
    """ansible-playbook 调用 argv（执行封装；不含任何密码/密钥）。

    SSH 连接参数（用户/密钥/端口/跳板）属配置边界（AE §8.4，G0 预检项）。
    真实密码只允许由 Ansible ``--ask-pass`` 从交互式终端读取，绝不作为
    Python 参数、inventory 值或 argv 内容传入。
    """
    argv = [executable or "ansible-playbook", str(playbook_path), "-i", str(inventory_path)]
    if limit is not None and limit != "all":
        argv += ["--limit", str(limit)]
    if remote_user:
        argv += ["--user", remote_user]
    if ask_pass:
        argv.append("--ask-pass")
    return argv


# --------------------------------------------------------------------------
# 执行计划（准备）
# --------------------------------------------------------------------------


@dataclass
class RunPlan:
    """一次采集的执行计划：playbook/inventory/主机/argv（封装调用就绪）。"""

    playbook_path: Path
    inventory_file: Path
    hosts: List[Any]                  # inventory.HostEntry 鸭子类型（name/ip）
    limit: Optional[str]
    metric_specs: List[CommandSpec]
    probe_command: str
    argv: List[str] = field(default_factory=list)
    cleanup_paths: Tuple[Path, ...] = field(default_factory=tuple)
    selection_kind: str = "unknown"


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parent.parent / _RUNTIME_DIR_NAME


def prepare_run(
    selection: Any,
    specs: Sequence[CommandSpec],
    runtime_dir: Optional[Path] = None,
) -> RunPlan:
    """allow-list 校验 → 生成 playbook 与 argv → RunPlan（不执行不连接）。

    selection：inventory.HostSelection 鸭子类型（.inventory_file/.hosts/
    .limit）；playbook 写入 runtime_dir（默认 <仓库根>/.runtime）。
    """
    validate_command_specs(specs)
    runtime_dir = Path(runtime_dir) if runtime_dir is not None else _default_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    playbook_path = runtime_dir / f"playbook-{uuid.uuid4().hex[:8]}.yml"
    text = generate_playbook(specs)
    try:
        playbook_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise CommandConfigError(
            f"playbook 写入失败: {playbook_path}（{exc}）"
        ) from exc
    plan = RunPlan(
        playbook_path=playbook_path,
        inventory_file=Path(selection.inventory_file),
        hosts=list(selection.hosts),
        limit=selection.limit,
        metric_specs=list(specs),
        probe_command=probe_mod.build_probe_command(),
        cleanup_paths=(
            (playbook_path, Path(selection.inventory_file))
            if getattr(selection, "kind", None) in {"local", "hosts"}
            else (playbook_path,)
        ),
        selection_kind=str(getattr(selection, "kind", "unknown")),
    )
    plan.argv = build_playbook_argv(
        plan.playbook_path, plan.inventory_file, plan.limit
    )
    return plan


# --------------------------------------------------------------------------
# fixture 模式（TD §10.2 / REQ-N-08：预录输出，零连接）
# --------------------------------------------------------------------------

_FIXTURE_DECLARATION = (
    "inspect.ansible_runner: 调试模式（fixture）：INSPECT_FIXTURE_DIR={dir}；"
    "返回预录输出，未发起任何连接，未执行真实 ansible-playbook"
)


def _resolve_fixture_dir(fixture_dir: Optional[Path]) -> Optional[Path]:
    """fixture 目录：参数优先，否则环境变量 INSPECT_FIXTURE_DIR（TD §10.2）。"""
    if fixture_dir is not None:
        return Path(fixture_dir)
    env = os.environ.get(FIXTURE_ENV_VAR)
    return Path(env) if env else None


def _read_fixture_text(path: Path) -> str:
    """读取夹具文本；剥离首部 `#` 注释行（RK-R2-06 文件头“非实测数据”标注）。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip().startswith("#"):
        i += 1
    return "\n".join(lines[i:]) + ("\n" if i < len(lines) else "")


def _read_fixture_rc(path: Path) -> Optional[int]:
    """读取可选 `<metric_id>.rc`（默认 0）；非法内容 → None（按缺省处理）。"""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# 结果分类（AE §6 失败与业务状态分离核心不变量）
# --------------------------------------------------------------------------


def classify_metric_result(
    metric_id: str,
    rc: Optional[int],
    stdout: str,
    stderr: str,
    required_commands: Sequence[str],
    probe_matrix: Dict[str, bool],
    preset_error: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """单指标结果分类（AE §6：技术失败 → UNKNOWN + error，不伪装业务）。

    优先级：preset_error（UNSUPPORTED_PROFILE）> 命令缺失
    （COMMAND_NOT_FOUND，AE §3）> 超时（TIMEOUT，AE §7）> 权限
    （PERMISSION_DENIED，AE §5）> 正常（rc/stdout 原样回传，
    rc 非零属业务语义数据——如 pgrep/grep 无匹配——由 normalize 解析）。

    命令缺失判定仅对**探测集合内**（TD §5.1，probe.PROBE_COMMANDS）的
    命令生效：探测集合是该判定唯一可测来源；head/cat 等指标命令中
    用到但未纳入探测集合的命令不做缺失判定（G0 预检可扩展探测集合）。
    """
    if preset_error is not None:
        return {
            "metric_id": metric_id,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "error": _error(preset_error["code"], preset_error["message"]),
        }
    missing = [
        c
        for c in required_commands
        if c in probe_mod.PROBE_COMMANDS and not probe_matrix.get(c, False)
    ]
    if missing:
        return {
            "metric_id": metric_id,
            "rc": None,
            "stdout": "",
            "stderr": "",
            "error": _error(
                ERROR_COMMAND_NOT_FOUND,
                f"能力探测未发现命令: {', '.join(missing)}（AE §3 → UNKNOWN，继续）",
            ),
        }
    if rc == TIMEOUT_RC:
        return {
            "metric_id": metric_id,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "error": _error(ERROR_TIMEOUT, "命令超时（timeout 退出码 124，AE §7）"),
        }
    low_err = (stderr or "").lower()
    if any(p in low_err for p in _PERMISSION_PATTERNS):
        return {
            "metric_id": metric_id,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "error": _error(
                ERROR_PERMISSION_DENIED,
                "权限不足（AE §5：单指标 → UNKNOWN，继续其余指标与主机）",
            ),
        }
    return {
        "metric_id": metric_id,
        "rc": rc,
        "stdout": stdout,
        "stderr": stderr,
        "error": None,
    }


def _error(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message, "metric_status": METRIC_ERROR_STATUS}


def build_host_result(
    host: Any,
    probe_matrix: Dict[str, bool],
    probe_ok: bool,
    metric_results: Sequence[Dict[str, Any]],
    *,
    host_error: Optional[Dict[str, str]] = None,
    elapsed_sec: float = 0.0,
) -> Dict[str, Any]:
    """主机级结果与 execution_status（AE §6 核心不变量）。

    - 连接失败 → ERROR，无业务结论（metrics=[]，AE §6：该主机无业务结论）；
    - probe 失败（bash 缺失等）→ ERROR，无业务结论（AE §3）；
    - 单主机总时长超限 → ERROR（TIMEOUT，AE §7），无业务结论；
    - 部分指标失败（权限/超时/命令缺失）→ PARTIAL，失败指标 UNKNOWN+error；
    - 全部成功 → SUCCESS。
    """
    if host_error is not None:
        return {
            "host": host.name,
            "ip": host.ip,
            "probe": probe_matrix,
            "probe_status": probe_mod.PROBE_FAILED if not probe_ok else probe_mod.PROBE_OK,
            "host_error": host_error,
            "execution_status": STATUS_ERROR,
            "metrics": [],
            "summary": {"total": len(metric_results), "executed": 0, "failed": len(metric_results)},
            "duration_sec": round(elapsed_sec, 3),
        }
    if not probe_ok:
        return {
            "host": host.name,
            "ip": host.ip,
            "probe": probe_matrix,
            "probe_status": probe_mod.PROBE_FAILED,
            "host_error": _error(
                ERROR_PROBE_FAILED,
                "能力探测失败（bash 不可用或探测未执行，AE §3 → 主机 ERROR，无业务结论）",
            ),
            "execution_status": STATUS_ERROR,
            "metrics": [],
            "summary": {"total": len(metric_results), "executed": 0, "failed": len(metric_results)},
            "duration_sec": round(elapsed_sec, 3),
        }
    failed = [m for m in metric_results if m["error"] is not None]
    status = STATUS_PARTIAL if failed else STATUS_SUCCESS
    return {
        "host": host.name,
        "ip": host.ip,
        "probe": probe_matrix,
        "probe_status": probe_mod.PROBE_OK,
        "host_error": None,
        "execution_status": status,
        "metrics": list(metric_results),
        "summary": {
            "total": len(metric_results),
            "executed": len(metric_results) - len(failed),
            "failed": len(failed),
        },
        "duration_sec": round(elapsed_sec, 3),
    }


def run_status_for_hosts(host_results: Sequence[Dict[str, Any]]) -> str:
    """运行级 execution_status（AE §6）：全部 ERROR → ERROR；
    任一主机非 SUCCESS → PARTIAL；否则 SUCCESS。"""
    if not host_results:
        return STATUS_ERROR
    if all(h["execution_status"] == STATUS_ERROR for h in host_results):
        return STATUS_ERROR
    if any(h["execution_status"] != STATUS_SUCCESS for h in host_results):
        return STATUS_PARTIAL
    return STATUS_SUCCESS


def host_deadline_exceeded(start_mono: float, now_mono: float) -> bool:
    """单主机总时长 300s 上限（AE §7）：超限 → 该主机失败（无业务结论）。"""
    return (now_mono - start_mono) > HOST_TIMEOUT_SEC


# --------------------------------------------------------------------------
# 执行（本任务仅 fixture 模式；真实执行 G0 前置）
# --------------------------------------------------------------------------


def _fixture_metric_result(
    host_dir: Path, spec: CommandSpec, probe_matrix: Dict[str, bool]
) -> Dict[str, Any]:
    if spec.command is None and spec.error_code == ERROR_UNSUPPORTED_PROFILE:
        return classify_metric_result(
            spec.metric_id,
            None,
            "",
            "",
            spec.required_commands,
            probe_matrix,
            preset_error={"code": ERROR_UNSUPPORTED_PROFILE, "message": spec.error_message or ""},
        )
    out_file = host_dir / f"{spec.metric_id}.out"
    if (host_dir / f"{spec.metric_id}.timeout").exists():
        return classify_metric_result(
            spec.metric_id, TIMEOUT_RC, "", "", spec.required_commands, probe_matrix
        )
    if not out_file.is_file():
        return classify_metric_result(
            spec.metric_id,
            None,
            "",
            "",
            spec.required_commands,
            probe_matrix,
            preset_error={
                "code": ERROR_DATA_MISSING,
                "message": f"夹具缺少预录输出: {out_file.name}（fixture 不完整）",
            },
        )
    stdout = _read_fixture_text(out_file)
    stderr = (
        _read_fixture_text(host_dir / f"{spec.metric_id}.stderr")
        if (host_dir / f"{spec.metric_id}.stderr").is_file()
        else ""
    )
    rc = _read_fixture_rc(host_dir / f"{spec.metric_id}.rc")
    if rc is None:
        rc = 0
    return classify_metric_result(
        spec.metric_id, rc, stdout, stderr, spec.required_commands, probe_matrix
    )


def _execute_fixture(plan: RunPlan, fixture_dir: Path) -> Dict[str, Any]:
    if not fixture_dir.is_dir():
        raise FixtureError(f"夹具目录不存在: {fixture_dir}")
    print(
        _FIXTURE_DECLARATION.format(dir=str(fixture_dir.resolve())),
        file=sys.stderr,
    )
    host_results: List[Dict[str, Any]] = []
    started = time.monotonic()
    for host in plan.hosts:
        host_dir = fixture_dir / host.name
        start = time.monotonic()
        if (host_dir / "CONNECTION_FAILED").is_file():
            host_results.append(
                build_host_result(
                    host,
                    {},
                    False,
                    [],
                    host_error=_error(
                        ERROR_CONNECTION_FAILED,
                        "连接失败（fixture 模拟；AE §6：该主机无业务结论）",
                    ),
                )
            )
            continue
        probe_text = ""
        if (host_dir / "probe.out").is_file():
            probe_text = _read_fixture_text(host_dir / "probe.out")
        probe_matrix = probe_mod.parse_probe_output(probe_text)
        probe_ok = probe_mod.probe_status(probe_matrix) == probe_mod.PROBE_OK
        if (host_dir / "PROBE_FAILED").is_file():
            probe_ok = False
        metric_results = [
            _fixture_metric_result(host_dir, spec, probe_matrix)
            for spec in plan.metric_specs
        ]
        host_results.append(
            build_host_result(
                host,
                probe_matrix,
                probe_ok,
                metric_results,
                elapsed_sec=time.monotonic() - start,
            )
        )
    return {
        "execution_status": run_status_for_hosts(host_results),
        "hosts": host_results,
        "fixture_mode": True,
        "fixture_dir": str(fixture_dir.resolve()),
        "duration_sec": round(time.monotonic() - started, 3),
    }


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_remote_user(value: Optional[str]) -> Optional[str]:
    """校验 Ansible 用户名；密码永远不接受为参数。"""
    if value is None or not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}", value):
        raise RealExecutionError(
            f"{REMOTE_USER_ENV_VAR} 含非法字符；只允许 Ansible 用户名安全字符"
        )
    return value


def _callback_text(value: Any, *, limit: int = 256 * 1024) -> str:
    """将 callback 字段转为有界文本；不把完整 Ansible 输出写入错误消息。"""
    if value is None:
        return ""
    if isinstance(value, list):
        value = "\n".join(str(item) for item in value)
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[output truncated by inspect]"


def _callback_host_items(value: Any):
    """兼容 json callback 的 host-map 与 host-list 形状。"""
    if isinstance(value, dict):
        yield from value.items()
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("host") or item.get("host_name")
            if name:
                yield str(name), item


def _load_callback_payload(stdout: str, *, return_code: Optional[int] = None) -> Dict[str, Any]:
    """Parse the structured Ansible JSON callback without trusting plain text."""
    text = (stdout or "").strip()
    if not text:
        raise RealExecutionError(
            "Ansible returned no structured callback",
            category="callback_empty",
            check="verify ANSIBLE_STDOUT_CALLBACK=json and process diagnostics",
            return_code=return_code,
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Some callback wrappers prepend diagnostics. Accept only a complete JSON
        # line with the expected top-level shape; never extract arbitrary substrings.
        payload = None
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "plays" in candidate:
                payload = candidate
                break
        if payload is None:
            raise RealExecutionError(
                "Ansible callback is not valid JSON; plain text was rejected as a fact source",
                category="callback_invalid_json",
                check="inspect callback JSON configuration and process diagnostics",
                return_code=return_code,
            )
    if not isinstance(payload, dict) or not isinstance(payload.get("plays"), list):
        raise RealExecutionError(
            "Ansible callback JSON is missing the plays structure",
            category="callback_schema_invalid",
            check="inspect callback JSON schema",
            return_code=return_code,
        )
    return payload


def _callback_error_for_unreachable() -> Dict[str, str]:
    """不回传 Ansible 原始 msg，避免 SSH 诊断意外携带秘密。"""
    return _error(ERROR_CONNECTION_FAILED, "Ansible 报告主机不可达或连接失败（无业务结论）")


def _cleanup_plan_files(plan: RunPlan) -> List[str]:
    """Remove generated files without Python 3.8-only APIs."""
    failures: List[str] = []
    for path in plan.cleanup_paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            # Retain only a sanitized basename; never expose filesystem details.
            failures.append(path.name or "runtime-file")
    return failures

def _validate_real_targets(plan: RunPlan) -> None:
    """校验 G0 真实执行只能触达已授权的两台 VM。"""
    targets = {str(getattr(host, "ip", "")) for host in plan.hosts}
    invalid = sorted(targets - REAL_ALLOWED_TARGETS)
    if not targets or invalid:
        shown = ", ".join(invalid) if invalid else "<empty>"
        raise RealExecutionError(
            "真实执行目标不在 G0 授权范围（仅允许 192.168.0.10 和 "
            f"192.168.0.101），已拒绝: {shown}"
        )


def _validate_local_selection(plan: RunPlan) -> None:
    """校验真实 local 模式只执行生成的 localhost inventory。"""
    if plan.selection_kind != "local":
        raise RealExecutionError(
            "本机真实执行要求显式 --local 选择；远程或自定义 inventory 不得使用本机门控"
        )
    if len(plan.hosts) != 1:
        raise RealExecutionError("本机真实执行只允许一个 localhost 目标")
    host = plan.hosts[0]
    if str(getattr(host, "name", "")) != "localhost" or str(
        getattr(host, "ip", "")
    ) != "127.0.0.1":
        raise RealExecutionError(
            "本机真实执行目标必须精确为 localhost/127.0.0.1"
        )
    try:
        inventory_text = plan.inventory_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise RealExecutionError("本机真实执行 inventory 无法读取") from exc
    expected = "localhost ansible_connection=local"
    if expected not in inventory_text.splitlines():
        raise RealExecutionError(
            "本机真实执行必须使用生成的 ansible_connection=local inventory"
        )


def _execute_real(plan: RunPlan) -> Dict[str, Any]:
    """Execute Ansible with the validated project-local Python 3.12 runtime."""
    is_local = plan.selection_kind == "local"
    result: Optional[Dict[str, Any]] = None
    primary_error: Optional[RealExecutionError] = None
    cleanup_diagnostic: Optional[Dict[str, Any]] = None
    try:
        if os.name == "nt" and os.environ.get("INSPECT_ALLOW_WINDOWS_REAL") != "1":
            raise RealExecutionError(
                "real Ansible execution requires a Linux or WSL control host",
                category="unsupported_control_platform",
                check="run from approved Linux/WSL control host",
            )

        if is_local:
            if os.environ.get(LOCAL_REAL_ENV_VAR) != REAL_EXEC_ENABLED:
                raise RealExecutionError(
                    f"local real execution requires both {REAL_EXEC_ENV_VAR}=1 and "
                    f"{LOCAL_REAL_ENV_VAR}=1",
                    category="real_gate_missing",
                    check="use inspect.sh --local rather than direct Python invocation",
                )
            _validate_local_selection(plan)
            if os.environ.get(REMOTE_USER_ENV_VAR):
                raise RealExecutionError(
                    "local mode must not receive a remote user",
                    category="local_security_boundary",
                    check="unset INSPECT_REMOTE_USER for local mode",
                )
            if _env_flag(ASK_PASS_ENV_VAR):
                raise RealExecutionError(
                    "local mode must not enable ask-pass",
                    category="local_security_boundary",
                    check="local mode uses ansible_connection=local",
                )
            remote_user = None
            ask_pass = False
        else:
            _validate_real_targets(plan)
            remote_user = _validate_remote_user(os.environ.get(REMOTE_USER_ENV_VAR))
            if remote_user is None:
                raise RealExecutionError(
                    "remote real execution requires an explicit remote user",
                    category="remote_user_missing",
                    check="set only the non-secret INSPECT_REMOTE_USER value",
                )
            ask_pass = _env_flag(ASK_PASS_ENV_VAR)
            if ask_pass and not getattr(sys.stdin, "isatty", lambda: False)():
                raise RealExecutionError(
                    "interactive password mode requires a controlling TTY",
                    category="interactive_password_unavailable",
                    check="use an interactive TTY or approved SSH agent/key",
                )

        runtime_root = Path(
            os.environ.get(
                "INSPECT_RUNTIME_ROOT",
                str(Path(__file__).resolve().parent.parent / "runtime"),
            )
        )
        try:
            dedicated_runtime = runtime_contract.resolve_runtime(runtime_root)
        except runtime_contract.RuntimeContractError as exc:
            raise RealExecutionError(
                str(exc),
                category=getattr(exc, "category", "dedicated_python_unavailable"),
                check="verify runtime/manifest.json, runtime/bin/python3.12, and sha256",
            ) from exc

        raw_argv = build_playbook_argv(
            plan.playbook_path,
            plan.inventory_file,
            plan.limit,
            remote_user=remote_user,
            ask_pass=ask_pass,
        )
        argv = dedicated_runtime.ansible_playbook_argv(raw_argv[1:])
        env = dedicated_runtime.ansible_environment(os.environ)
        env["ANSIBLE_STDOUT_CALLBACK"] = ANSIBLE_STDOUT_CALLBACK
        env["ANSIBLE_CALLBACK_PLUGINS"] = str(Path(__file__).resolve().parent / "callback_plugins")
        env["ANSIBLE_RETRY_FILES_ENABLED"] = "False"
        for secret_name in ("ANSIBLE_PASSWORD", "ANSIBLE_NET_PASSWORD", "SSHPASS"):
            env.pop(secret_name, None)

        timeout = HOST_TIMEOUT_SEC * max(len(plan.hosts), 1) + REAL_PROCESS_TIMEOUT_GRACE_SEC
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                stdin=None if ask_pass else subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise RealExecutionError(
                "Ansible executable is missing from the project runtime",
                category="ansible_executable_missing",
                check="install ansible-core into the approved offline runtime",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RealExecutionError(
                f"Ansible control process exceeded {timeout}s",
                category="execution_timeout",
                check="inspect sanitized callback and timeout conditions",
            ) from exc
        except OSError as exc:
            raise RealExecutionError(
                "Ansible control process could not be started",
                category="command_execution_failed",
                check="verify the dedicated Python and Ansible runtime",
            ) from exc

        payload = _load_callback_payload(
            completed.stdout, return_code=int(completed.returncode)
        )
        host_results = _parse_callback_results(plan, payload, time.monotonic() - started)
        result = {
            "execution_status": run_status_for_hosts(host_results),
            "hosts": host_results,
            "real_mode": True,
            "process_rc": int(completed.returncode),
            "duration_sec": round(time.monotonic() - started, 3),
        }
        if completed.returncode != 0:
            result["diagnostic"] = {
                "category": "ansible_process_failed",
                "return_code": int(completed.returncode),
                "check": "inspect callback and playbook/module diagnostics",
            }
    except RealExecutionError as exc:
        primary_error = exc
        raise
    finally:
        failures = _cleanup_plan_files(plan)
        if failures:
            cleanup_diagnostic = {
                "category": "runtime_cleanup_failed",
                "return_code": None,
                "check": "remove generated runtime files manually",
                "files": failures,
            }
            if primary_error is not None:
                primary_error.cleanup_diagnostic = cleanup_diagnostic
    if result is not None and cleanup_diagnostic is not None:
        result["cleanup_diagnostic"] = cleanup_diagnostic
    return result or {}

def _parse_callback_results(
    plan: RunPlan, payload: Dict[str, Any], elapsed_sec: float
) -> List[Dict[str, Any]]:
    """把 json callback 的 task/host 结果映射为既有 runner 数据形状。"""
    states: Dict[str, Dict[str, Any]] = {
        str(host.name): {
            "host": host,
            "probe_matrix": {},
            "probe_ok": False,
            "probe_seen": False,
            "host_error": None,
            "metrics": {},
        }
        for host in plan.hosts
    }
    spec_by_id = {spec.metric_id: spec for spec in plan.metric_specs}

    for play_entry in payload.get("plays", []):
        if not isinstance(play_entry, dict):
            continue
        for task_entry in play_entry.get("tasks", []):
            if not isinstance(task_entry, dict):
                continue
            task = task_entry.get("task") or {}
            task_name = str(task.get("name", ""))
            for host_name, raw in _callback_host_items(task_entry.get("hosts")):
                state = states.get(host_name)
                if state is None or not isinstance(raw, dict):
                    continue
                if raw.get("unreachable"):
                    state["host_error"] = _callback_error_for_unreachable()
                    continue
                if task_name.startswith("probe:"):
                    state["probe_seen"] = True
                    text = _callback_text(raw.get("stdout"))
                    matrix = probe_mod.parse_probe_output(text)
                    state["probe_matrix"] = matrix
                    state["probe_ok"] = (
                        not raw.get("failed")
                        and probe_mod.probe_status(matrix) == probe_mod.PROBE_OK
                    )
                    if not state["probe_ok"] and raw.get("failed"):
                        state["host_error"] = _error(
                            ERROR_PROBE_FAILED,
                            "能力探测任务失败（Ansible callback；无业务结论）",
                        )
                    continue
                if not task_name.startswith("metric:"):
                    continue
                match = re.search(r"metric:\s+([^（(\s]+)", task_name)
                if not match:
                    continue
                metric_id = match.group(1)
                spec = spec_by_id.get(metric_id)
                if spec is None:
                    continue
                rc = raw.get("rc")
                if isinstance(rc, bool):
                    rc = int(rc)
                elif rc is not None:
                    try:
                        rc = int(rc)
                    except (TypeError, ValueError):
                        rc = None
                if raw.get("failed") and rc is None:
                    rc = 1
                state["metrics"][metric_id] = classify_metric_result(
                    metric_id,
                    rc,
                    _callback_text(raw.get("stdout")),
                    _callback_text(raw.get("stderr")),
                    spec.required_commands,
                    state["probe_matrix"],
                )

    stats = payload.get("stats") or {}
    if isinstance(stats, dict):
        for host_name, stat in stats.items():
            state = states.get(str(host_name))
            if state is not None and isinstance(stat, dict) and stat.get("unreachable", 0):
                state["host_error"] = _callback_error_for_unreachable()

    results: List[Dict[str, Any]] = []
    for state in states.values():
        metrics: List[Dict[str, Any]] = []
        for spec in plan.metric_specs:
            if spec.command is None and spec.error_code == ERROR_UNSUPPORTED_PROFILE:
                metrics.append(
                    classify_metric_result(
                        spec.metric_id,
                        None,
                        "",
                        "",
                        spec.required_commands,
                        state["probe_matrix"],
                        preset_error={
                            "code": ERROR_UNSUPPORTED_PROFILE,
                            "message": spec.error_message or "",
                        },
                    )
                )
                continue
            if spec.metric_id in state["metrics"]:
                metrics.append(state["metrics"][spec.metric_id])
                continue
            metrics.append(
                classify_metric_result(
                    spec.metric_id,
                    None,
                    "",
                    "",
                    spec.required_commands,
                    state["probe_matrix"],
                    preset_error={
                        "code": ERROR_DATA_MISSING,
                        "message": "Ansible callback 缺少该指标任务结果",
                    },
                )
            )
        results.append(
            build_host_result(
                state["host"],
                state["probe_matrix"],
                state["probe_ok"] if state["probe_seen"] else False,
                metrics,
                host_error=state["host_error"],
                elapsed_sec=elapsed_sec,
            )
        )
    return results


def execute_plan(
    plan: RunPlan,
    fixture_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """执行计划并回传结果（AE §6 分类）。

    - INSPECT_FIXTURE_DIR（参数或环境变量）→ fixture 模式：返回预录
      输出，stderr 声明调试模式，**不产生任何连接**（TD §10.2，REQ-N-08）；
    - 未设置 fixture 且 INSPECT_ENABLE_REAL=1 → 显式启用真实 Ansible，
      仅消费 json callback，凭据由 Ansible 原生交互机制处理；
    - 其余情况 → ExecutionNotReadyError（G0 前置，退出码 10）。
    """
    resolved = _resolve_fixture_dir(fixture_dir)
    if resolved is not None:
        return _execute_fixture(plan, resolved)
    if os.environ.get(REAL_EXEC_ENV_VAR) != REAL_EXEC_ENABLED:
        raise ExecutionNotReadyError(
            "真实 ansible-playbook 执行未启用：需 G0 预检"
            "（ansible-core 版本 / SSH 连接参数 / become 方式，AE §8；"
            "默认不执行真实 playbook）。"
            f"调试/验证请设置 {FIXTURE_ENV_VAR}（fixture 模式，零连接）；"
            f"现场只读执行需显式设置 {REAL_EXEC_ENV_VAR}=1。"
        )
    return _execute_real(plan)


def run(
    selection: Any,
    specs: Sequence[CommandSpec],
    fixture_dir: Optional[Path] = None,
    runtime_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """prepare_run + execute_plan 便捷入口（cli 编排挂接点）。"""
    plan = prepare_run(selection, specs, runtime_dir=runtime_dir)
    return execute_plan(plan, fixture_dir=fixture_dir)


__all__ = [
    "CommandConfigError",
    "CommandNotAllowedError",
    "CommandSpec",
    "ERROR_CODES",
    "ERROR_COMMAND_NOT_FOUND",
    "ERROR_CONNECTION_FAILED",
    "ERROR_DATA_MISSING",
    "ERROR_PERMISSION_DENIED",
    "ERROR_PROBE_FAILED",
    "ERROR_TIMEOUT",
    "ERROR_UNSUPPORTED_PROFILE",
    "ExecutionNotReadyError",
    "FixtureError",
    "REAL_EXEC_ENV_VAR",
    "REMOTE_USER_ENV_VAR",
    "ASK_PASS_ENV_VAR",
    "LOCAL_REAL_ENV_VAR",
    "REAL_ALLOWED_TARGETS",
    "RealExecutionError",
    "FIXTURE_ENV_VAR",
    "HOST_TIMEOUT_SEC",
    "LOG_METRIC_TIMEOUT_SEC",
    "METRIC_ERROR_STATUS",
    "METRIC_TIMEOUT_SEC",
    "PROBE_TIMEOUT_SEC",
    "RunPlan",
    "STATUS_ERROR",
    "STATUS_PARTIAL",
    "STATUS_SUCCESS",
    "TIMEOUT_RC",
    "build_metric_command_specs",
    "build_playbook_argv",
    "build_host_result",
    "classify_metric_result",
    "execute_plan",
    "generate_playbook",
    "host_deadline_exceeded",
    "parse_binaries",
    "prepare_run",
    "run",
    "run_status_for_hosts",
    "validate_command_specs",
]
