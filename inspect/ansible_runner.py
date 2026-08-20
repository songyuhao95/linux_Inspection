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
from inspect.modules import DEFAULT_COLLECTION_MODULE_IDS, default_registry

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
# 密码 inventory 的首次 SSH 连接不能依赖人工预先写入 known_hosts：Ansible
# 自身的 host-key 检查会在 sshpass 介入前直接拒绝。关闭 Ansible 的重复检查，
# 同时让 OpenSSH 采用 accept-new：首次连接自动记录，已知密钥变更仍拒绝。
ANSIBLE_HOST_KEY_CHECKING = "False"
ANSIBLE_SSH_COMMON_ARGS = "-o StrictHostKeyChecking=accept-new"
REAL_PROCESS_TIMEOUT_GRACE_SEC = 30
MAX_CAPTURED_ERROR_CHARS = 1200

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
    # Substituted command binaries captured at spec-build time.  Profile
    # placeholders in command position (e.g. ``{nginx_bin}``) are resolved
    # only after substitution, so the allow-list validator uses this set when
    # present and falls back to the template binaries otherwise.
    allowed_binaries: Tuple[str, ...] = ()
    # Nginx discovery commands are generated by this module and deliberately
    # use shell variables/command substitutions to carry paths from the
    # target process/config into the following read-only check.  This is not
    # an escape hatch for profile text: only the internal Nginx builder sets
    # it, and validate_command_specs still enforces the metric/timeout/become
    # registry boundary.
    trusted_generated_shell: bool = False


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
        "command": "df -hT",
        "profile_keys": (),
        "become": False,
        "anchor": "MR §5.6 磁盘行 + TD §5.2 local.filesystem.used_percent",
    },
    "local.filesystem.inode_used_percent": {
        "command": "df -i",
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
    # ---- Nginx 中间件（nginx-p0-v1；安徽农金Nginx、Keepalived运维巡检手册）----
    "local.nginx.process.present": {
        # The bracket expression prevents pgrep from matching the shell that
        # contains this command.  Only the actual Nginx master/worker process
        # names count; a command line mentioning an nginx path is not proof
        # that Nginx is running.
        "command": "pgrep -fa '[n]ginx: (master|worker) process'",
        "profile_keys": (),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Nginx本节点服务」行",
    },
    "local.nginx.version": {
        "command": "{nginx_bin} -v 2>&1",
        "profile_keys": ("nginx_bin",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Nginx版本」行",
    },
    "local.nginx.config.valid": {
        "command": "{nginx_bin} -t -e {nginx_error_log} -c {nginx_conf}",
        "profile_keys": ("nginx_bin", "nginx_error_log", "nginx_conf"),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Nginx配置有效性」行",
    },
    "local.nginx.port.listening": {
        "command": (
            "ss -tlnp | grep ':{nginx_port}'; "
            "curl -sS -I --connect-timeout 3 http://127.0.0.1:{nginx_port}/ | head -n 1"
        ),
        "profile_keys": ("nginx_port",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Nginx端口与本地访问」行",
    },
    "local.nginx.error_log.key_evidence": {
                "command": (
            "ls -1 {nginx_error_log} 2>/dev/null; "
            "tail -n 1000 {nginx_error_log} | egrep -i "
            "'emerg|alert|crit|error|permission denied|bind\\(|connect\\(\\) failed|"
            "upstream timed out' | tail -n 20"
        ),
        "profile_keys": ("nginx_error_log",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「关键日志」行",
    },
    "local.nginx.connections.status": {
        "command": "curl -sS --connect-timeout 3 http://127.0.0.1:{nginx_port}/nginx_status",
        "profile_keys": ("nginx_port",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P1「Nginx连接状态」行",
    },
    "local.nginx.access_log.status_codes": {
        "command": (
            "ls -1 {nginx_access_log} 2>/dev/null; "
            "tail -n 1000 {nginx_access_log} | grep -E ' [1-5][0-9][0-9] '"
        ),
        "profile_keys": ("nginx_access_log",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P1「访问日志状态码」行",
    },
    "local.nginx.config.baseline": {
        "command": (
            "ls -1 {nginx_conf} 2>/dev/null; "
            "grep -E 'worker_processes|worker_rlimit_nofile|worker_connections|"
            "use epoll|multi_accept|keepalive_timeout|client_max_body_size|limit_req|"
            "limit_conn' {nginx_conf}"
        ),
        "profile_keys": ("nginx_conf",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P1「Nginx配置基线」行",
    },
    "local.nginx.security.baseline": {
        "command": (
            "ls -1 {nginx_conf} 2>/dev/null; "
            "grep -E 'server_tokens|autoindex|X-Frame-Options|X-Content-Type-Options|"
            "Content-Security-Policy|request_method' {nginx_conf}"
        ),
        "profile_keys": ("nginx_conf",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P1「安全配置基线」行",
    },
    # ---- Keepalived 中间件（keepalived-p0-v1） ----
    "local.keepalived.process.present": {
        "command": "pgrep -fa '(^|[[:space:]/])keepalived[[:space:]]'",
        "profile_keys": (),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Keepalived本节点服务」行",
    },
    "local.keepalived.version": {
        "command": "{keepalived_bin} -v 2>&1",
        "profile_keys": ("keepalived_bin",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 环境信息「Keepalived版本」行",
    },
    "local.keepalived.vip.bound": {
        "command": "ip -brief addr; grep -E 'state|virtual_ipaddress|interface' {keepalived_conf}",
        "profile_keys": ("keepalived_conf",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「VIP绑定状态」行",
    },
    "local.keepalived.vip.access": {
        "command": "curl -sS -I --connect-timeout 3 http://{keepalived_vip}:{keepalived_port}/",
        "profile_keys": ("keepalived_vip", "keepalived_port"),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「VIP访问」行",
    },
    "local.keepalived.config.baseline": {
        "command": "ls -1 {keepalived_conf} 2>/dev/null; grep -E 'state|interface|virtual_router_id|priority|advert_int|virtual_ipaddress|script|track_script' {keepalived_conf}",
        "profile_keys": ("keepalived_conf",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「Keepalived配置基线」行",
    },
    "local.keepalived.healthcheck.script": {
        "command": "grep -E 'script|track_script' {keepalived_conf}; test -r {keepalived_conf}",
        "profile_keys": ("keepalived_conf",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「健康检查脚本」行",
    },
    "local.keepalived.error_log.key_evidence": {
        "command": "tail -n 1000 {keepalived_log} | grep -Ei 'Entering MASTER|Entering BACKUP|Entering FAULT|script.*failed|VRRP'",
        "profile_keys": ("keepalived_log",),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P0「关键日志」行",
    },
    "local.keepalived.capability.stability": {
        "command": "getcap {keepalived_bin}; systemctl show keepalived-opt -p AmbientCapabilities -p CapabilityBoundingSet; tail -n 50 {keepalived_log}",
        "profile_keys": ("keepalived_bin", "keepalived_log"),
        "become": False,
        "anchor": "安徽农金Nginx、Keepalived运维巡检手册 P1「Keepalived能力与漂移稳定性」行",
    },
    # ---- Elasticsearch 中间件（elasticsearch-p0-p1-v1） ----
    "local.elasticsearch.process.present": {
        "command": "pgrep -fa '(^|[[:space:]/])elasticsearch[[:space:]]|org\\.elasticsearch\\.bootstrap\\.Elasticsearch'",
        "profile_keys": (), "become": False,
        "anchor": "安徽农金Elasticsearch运维巡检手册 P0「服务/进程」行",
    },
}

# The remaining Elasticsearch commands are generated only after the target
# process/config is discovered.  The placeholder is never executed; it keeps
# every metric present in the single command registry used by validation.
for _es_metric_id in (
    "local.elasticsearch.version", "local.elasticsearch.cluster.health",
    "local.elasticsearch.nodes.online", "local.elasticsearch.nodes.cpu",
    "local.elasticsearch.nodes.memory", "local.elasticsearch.nodes.disk",
    "local.elasticsearch.disk.watermark", "local.elasticsearch.shards.unassigned",
    "local.elasticsearch.service.port", "local.elasticsearch.heap.gc",
    "local.elasticsearch.thread_pool.rejected", "local.elasticsearch.cluster.settings",
    "local.elasticsearch.discovery.config", "local.elasticsearch.indices.health",
    "local.elasticsearch.slowlog.key_evidence", "local.elasticsearch.security.accounts",
    "local.elasticsearch.certificate.validity", "local.elasticsearch.snapshot.repository",
    "local.elasticsearch.system.parameters",
):
    _COMMAND_TEMPLATES[_es_metric_id] = {
        "command": "printf 'Elasticsearch dynamic command'",
        "profile_keys": (),
        "become": False,
        "anchor": "安徽农金Elasticsearch运维巡检手册 P0/P1 指标动态采集",
    }

# 日志类指标（超时 15s，AE §7 / TD §5.2 超时列）
_LOG_METRIC_IDS = {
    "local.logs.key_evidence",
    "local.nginx.error_log.key_evidence",
    "local.nginx.access_log.status_codes",
    "local.keepalived.error_log.key_evidence",
    "local.keepalived.capability.stability",
    "local.elasticsearch.heap.gc",
    "local.elasticsearch.slowlog.key_evidence",
}


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
    if key == "nginx_bin":
        # nginx 可执行文件路径或命令名（手动路径 /usr/sbin/nginx、
        # 源码路径 /opt/nginx/sbin/nginx）；安全字符集防注入
        if not isinstance(value, str) or not _SAFE_WORD.fullmatch(value) or not value:
            raise CommandConfigError(f"profile nginx_bin 非法: {value!r}")
        return value
    if key == "nginx_port":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise CommandConfigError(f"profile nginx_port 必须为 1..65535 整数: {value!r}")
        return str(value)
    if key in ("nginx_conf", "nginx_error_log", "nginx_access_log"):
        if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
            raise CommandConfigError(
                f"profile {key} 路径非法（需绝对路径，仅限安全字符）: {value!r}"
            )
        return value
    if key == "keepalived_bin":
        if not isinstance(value, str) or not _SAFE_WORD.fullmatch(value) or not value:
            raise CommandConfigError(f"profile keepalived_bin 非法: {value!r}")
        return value
    if key in ("keepalived_conf", "keepalived_log"):
        if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
            raise CommandConfigError(
                f"profile {key} 路径非法（需绝对路径，仅限安全字符）: {value!r}"
            )
        return value
    if key == "keepalived_port":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise CommandConfigError(f"profile keepalived_port 必须为 1..65535 整数: {value!r}")
        return str(value)
    if key == "keepalived_vip":
        if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f:.%]+(?:/[0-9]+)?", value):
            raise CommandConfigError(f"profile keepalived_vip 非法: {value!r}")
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


_NGINX_GENERATED_ALLOWED_BINARIES = (
    "pgrep", "ps", "sed", "head", "tail", "grep", "ss", "curl", "ls",
)
_NGINX_UNSAFE_GENERATED_TOKENS = re.compile(
    r"\b(?:rm|rmdir|mkfs|dd|shutdown|reboot|poweroff|sudo|ssh|scp|nc|ncat|"
    r"wget|python|perl|ruby|php|eval|exec|source|chmod|chown|mount|umount)\b"
)

_KEEPALIVED_GENERATED_ALLOWED_BINARIES = (
    "pgrep", "ps", "sed", "head", "tail", "grep", "egrep", "ls", "ip",
    "curl", "awk", "getcap", "systemctl", "test",
)
_KEEPALIVED_UNSAFE_GENERATED_TOKENS = re.compile(
    r"\b(?:rm|rmdir|mkfs|dd|shutdown|reboot|poweroff|sudo|ssh|scp|nc|ncat|"
    r"wget|python|perl|ruby|php|eval|exec|source|chmod|chown|mount|umount)\b"
)

_ELASTICSEARCH_GENERATED_ALLOWED_BINARIES = (
    "pgrep", "ps", "sed", "head", "tail", "grep", "egrep", "curl", "ls",
    "ss", "cat", "free", "su", "openssl", "test", "printf", "awk",
)
_ELASTICSEARCH_UNSAFE_GENERATED_TOKENS = re.compile(
    r"\b(?:rm|rmdir|mkfs|dd|shutdown|reboot|poweroff|sudo|ssh|scp|nc|ncat|"
    r"wget|python|perl|ruby|php|eval|exec|source|chmod|chown|mount|umount)\b"
)


def _nginx_candidates(profile: Dict[str, Any], key: str) -> List[str]:
    """Validate inspect.conf candidates without treating them as auth data."""
    raw = profile.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    elif key == "nginx_port" and isinstance(raw, int) and not isinstance(raw, bool):
        # Keep compatibility with the historical profile shape;
        # inspect.conf itself always supplies strings.
        raw = [str(raw)]
    if not isinstance(raw, list):
        raise CommandConfigError(f"inspect.conf {key} 必须为候选值列表: {raw!r}")
    result: List[str] = []
    for item in raw:
        if key == "nginx_port":
            if not isinstance(item, str) or not re.fullmatch(r"[0-9]+", item):
                raise CommandConfigError(f"inspect.conf nginx_port 必须为数字: {item!r}")
            _validate_profile_value(key, int(item))
            result.append(item)
        elif key in {"nginx_bin", "nginx_conf", "nginx_error_log", "nginx_access_log"}:
            result.append(_validate_profile_value(key, item))
        else:
            raise CommandConfigError(f"不支持的 Nginx 候选参数: {key}")
    return result


def _nginx_shell_words(values: Sequence[str]) -> str:
    """Build a safe shell word list from values already profile-validated."""
    return " ".join(values)


def _is_runtime_nginx_profile(profile: Dict[str, Any]) -> bool:
    """Identify the list-shaped profile loaded from inspect.conf.

    The scalar-shaped legacy profile remains supported for fixture/test callers
    and old library integrations.  The CLI always supplies the list-shaped
    inspect.conf result, including an all-empty result when no fallbacks are
    configured, so production execution always uses auto-discovery.
    """
    keys = (
        "nginx_bin", "nginx_conf", "nginx_error_log", "nginx_access_log",
        "nginx_port", "nginx_version",
    )
    return any(key in profile for key in keys) and all(
        key not in profile or isinstance(profile.get(key), list) for key in keys
    )


def _keepalived_candidates(profile: Dict[str, Any], key: str) -> List[str]:
    """Validate Keepalived inspect.conf candidates."""
    raw = profile.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise CommandConfigError(f"inspect.conf {key} 必须为候选值列表: {raw!r}")
    result: List[str] = []
    for item in raw:
        if key == "keepalived_port":
            if not isinstance(item, str) or not re.fullmatch(r"[0-9]+", item):
                raise CommandConfigError(f"inspect.conf keepalived_port 必须为数字: {item!r}")
            _validate_profile_value(key, int(item))
            result.append(item)
        elif key in {"keepalived_bin", "keepalived_conf", "keepalived_log"}:
            result.append(_validate_profile_value(key, item))
        elif key == "keepalived_vip":
            result.append(_validate_profile_value(key, item))
        else:
            raise CommandConfigError(f"不支持的 Keepalived 候选参数: {key}")
    return result


def _keepalived_shell_words(values: Sequence[str]) -> str:
    return " ".join(values)


def _is_runtime_keepalived_profile(profile: Dict[str, Any]) -> bool:
    keys = (
        "keepalived_bin", "keepalived_conf", "keepalived_log", "keepalived_vip",
        "keepalived_port", "keepalived_version",
    )
    return any(key in profile for key in keys) and all(
        key not in profile or isinstance(profile.get(key), list) for key in keys
    )


def _elasticsearch_candidates(profile: Dict[str, Any], key: str) -> List[str]:
    """Validate Elasticsearch inspect.conf candidate values.

    This is intentionally separate from the legacy product profile validator:
    inspect.conf values are already parsed into lists and include URLs, ports,
    glob paths and version strings.
    """
    raw = profile.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise CommandConfigError(f"inspect.conf {key} 必须为候选值列表: {raw!r}")
    result: List[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise CommandConfigError(f"inspect.conf {key} 候选值必须为非空字符串: {item!r}")
        if key.endswith("_port") or key in {"elasticsearch_expected_nodes"}:
            if not re.fullmatch(r"[0-9]+", item):
                raise CommandConfigError(f"inspect.conf {key} 必须为数字: {item!r}")
        elif key in {
            "elasticsearch_bin", "elasticsearch_conf", "elasticsearch_log",
            "elasticsearch_gc_log", "elasticsearch_data", "elasticsearch_backup",
            "elasticsearch_auth_file", "elasticsearch_cert",
        }:
            if not _SAFE_PATH.fullmatch(item):
                raise CommandConfigError(f"inspect.conf {key} 路径非法: {item!r}")
        elif key == "elasticsearch_endpoint":
            if not re.fullmatch(r"https?://[A-Za-z0-9_.:%+\-/]+", item):
                raise CommandConfigError(f"inspect.conf {key} URL 非法: {item!r}")
        elif key in {"elasticsearch_system_user", "elasticsearch_snapshot_repo"}:
            if not re.fullmatch(r"[A-Za-z0-9_.@+-]+", item):
                raise CommandConfigError(f"inspect.conf {key} 值非法: {item!r}")
        elif key == "elasticsearch_version":
            if not re.fullmatch(r"[A-Za-z0-9_.+\-/]+", item):
                raise CommandConfigError(f"inspect.conf {key} 版本值非法: {item!r}")
        elif key == "elasticsearch_seed_hosts":
            if not re.fullmatch(r"[A-Za-z0-9_.:%+\-/]+", item):
                raise CommandConfigError(f"inspect.conf {key} 节点值非法: {item!r}")
        else:
            if not _SAFE_WORD.fullmatch(item):
                raise CommandConfigError(f"inspect.conf {key} 值非法: {item!r}")
        result.append(item)
    return result


def _elasticsearch_shell_words(values: Sequence[str]) -> str:
    return " ".join(values)


def _is_runtime_elasticsearch_profile(profile: Dict[str, Any]) -> bool:
    keys = (
        "elasticsearch_bin", "elasticsearch_conf", "elasticsearch_log",
        "elasticsearch_gc_log", "elasticsearch_data", "elasticsearch_backup",
        "elasticsearch_endpoint", "elasticsearch_http_port",
        "elasticsearch_transport_port", "elasticsearch_version",
        "elasticsearch_expected_nodes", "elasticsearch_seed_hosts",
        "elasticsearch_system_user", "elasticsearch_auth_file",
        "elasticsearch_cert", "elasticsearch_snapshot_repo",
    )
    return any(key in profile for key in keys) and all(
        key not in profile or isinstance(profile.get(key), list) for key in keys
    )


def _elasticsearch_discovery_prefix(profile: Dict[str, Any]) -> str:
    """Discover ES home/config/log/API paths from the running JVM first."""
    bins = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_bin")) or ":"
    confs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_conf")) or ":"
    logs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_log")) or ":"
    gc_logs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_gc_log")) or ":"
    certs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_cert")) or ":"
    endpoints = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_endpoint")) or ":"
    auths = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_auth_file")) or ":"
    http_ports = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_http_port")) or "9200"
    transport_ports = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_transport_port")) or "9300"
    system_users = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_system_user")) or "es"
    return "; ".join([
        "es_process_line=$(pgrep -fa '(^|[[:space:]/])elasticsearch[[:space:]]|org\\.elasticsearch\\.bootstrap\\.Elasticsearch' | head -n 1)",
        "es_home=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/.*-Des.path.home=([^[:space:]]+).*/\\1/p')",
        "es_conf_dir=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/.*-Des.path.conf=([^[:space:]]+).*/\\1/p')",
        "es_bin=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/.*[[:space:]]([^[:space:]]*\\/bin\\/elasticsearch)([[:space:]]|$).*/\\1/p')",
        "if test -n \"$es_home\" && test -x \"$es_home/bin/elasticsearch\"; then es_bin=\"$es_home/bin/elasticsearch\"; fi",
        f"if test -z \"$es_bin\" || ! test -x \"$es_bin\"; then for p in {bins}; do if test -x \"$p\"; then es_bin=\"$p\"; break; fi; done; fi",
        "if test -z \"$es_conf_dir\" && test -n \"$es_home\"; then es_conf_dir=\"$es_home/config\"; fi",
        "es_conf=\"\"; if test -n \"$es_conf_dir\" && test -f \"$es_conf_dir/elasticsearch.yml\"; then es_conf=\"$es_conf_dir/elasticsearch.yml\"; fi",
        f"if test -z \"$es_conf\"; then for p in {confs}; do if test -f \"$p\"; then es_conf=\"$p\"; break; fi; done; fi",
        "es_pid=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/^([0-9]+).*/\\1/p')",
        "es_user=\"\"; if test -n \"$es_pid\"; then es_user=$(ps -o user= -p \"$es_pid\" | sed -n 's/[[:space:]]//gp'); fi",
        f"if test -z \"$es_user\"; then for p in {system_users}; do es_user=\"$p\"; break; done; fi",
        "es_log_dir=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/.*-Des.path.logs=([^[:space:]]+).*/\\1/p')",
        "if test -z \"$es_log_dir\" && test -n \"$es_home\"; then es_log_dir=\"$es_home/logs\"; fi",
        "es_log=\"\"; if test -n \"$es_log_dir\"; then for p in \"$es_log_dir\"/*; do if test -f \"$p\"; then es_log=\"$p\"; break; fi; done; fi",
        f"if test -z \"$es_log\"; then for p in {logs}; do if test -f \"$p\"; then es_log=\"$p\"; break; fi; done; fi",
        "es_gc_log=\"\"; if test -n \"$es_log_dir\"; then for p in \"$es_log_dir\"/gc.log*; do if test -f \"$p\"; then es_gc_log=\"$p\"; break; fi; done; fi",
        f"if test -z \"$es_gc_log\"; then for p in {gc_logs}; do if test -f \"$p\"; then es_gc_log=\"$p\"; break; fi; done; fi",
        "es_http_port=$(test -n \"$es_conf\" && sed -nE 's/^[[:space:]]*http.port:[[:space:]]*([0-9]+).*/\\1/p' \"$es_conf\" | head -n 1)",
        f"if test -z \"$es_http_port\"; then es_http_port={http_ports}; fi",
        "es_transport_port=$(test -n \"$es_conf\" && sed -nE 's/^[[:space:]]*transport.port:[[:space:]]*([0-9]+).*/\\1/p' \"$es_conf\" | head -n 1)",
        f"if test -z \"$es_transport_port\"; then es_transport_port={transport_ports}; fi",
        "es_endpoint=\"\"",
        "es_bind_host=$(test -n \"$es_conf\" && sed -nE 's/^[[:space:]]*(network.host|http.host|network.bind_host):[[:space:]]*([^#[:space:]]+).*/\\2/p' \"$es_conf\" | head -n 1)",
        "case \"$es_bind_host\" in 0.0.0.0|_site_|_local_|\\[::\\]|::) es_bind_host=127.0.0.1;; esac",
        "if test -n \"$es_bind_host\"; then es_endpoint=\"https://$es_bind_host:$es_http_port\"; fi",
        f"if test -z \"$es_endpoint\"; then for p in {endpoints}; do es_endpoint=\"$p\"; break; done; fi",
        "if test -z \"$es_endpoint\"; then es_endpoint=\"https://127.0.0.1:$es_http_port\"; fi",
        "es_auth=\"\"; for p in " + auths + "; do if test -f \"$p\"; then es_auth=\"--netrc-file $p\"; break; fi; done",
        "es_cert=\"\"; if test -n \"$es_conf\"; then es_cert=$(grep -Eo '/[^[:space:]]+\\.(crt|pem)' \"$es_conf\" | head -n 1); fi",
        f"if test -z \"$es_cert\"; then for p in {certs}; do if test -f \"$p\"; then es_cert=\"$p\"; break; fi; done; fi",
    ])


def _es_curl(path: str) -> str:
    return f"curl -k -sS --connect-timeout 3 --max-time 10 $es_auth \"$es_endpoint{path}\""


def _build_elasticsearch_metric_command(metric_id: str, profile: Dict[str, Any]) -> str:
    prefix = _elasticsearch_discovery_prefix(profile)
    if metric_id == "local.elasticsearch.version":
        return prefix + "; if test -z \"$es_process_line\" || test -z \"$es_bin\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_RUNNING_NOT_FOUND; else \"$es_bin\" --version 2>&1; fi"
    if metric_id == "local.elasticsearch.cluster.health":
        return prefix + "; if test -z \"$es_endpoint\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_ENDPOINT_NOT_FOUND; else " + _es_curl("/_cluster/health?pretty") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'; fi"
    if metric_id == "local.elasticsearch.nodes.online":
        return prefix + "; " + _es_curl("/_cat/nodes?v&h=name,ip,node.role,master,heap.percent,cpu,load_1m,disk.used_percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.cpu":
        return prefix + "; " + _es_curl("/_cat/nodes?v&h=name,ip,cpu,load_1m,load_5m,load_15m") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.memory":
        return prefix + "; " + _es_curl("/_cat/nodes?v&h=name,heap.percent,ram.percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.disk":
        return prefix + "; " + _es_curl("/_cat/allocation?v") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.disk.watermark":
        return prefix + "; " + _es_curl("/_cluster/settings?include_defaults=true&filter_path=**.watermark*") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.shards.unassigned":
        return prefix + "; " + _es_curl("/_cat/shards?v&h=index,shard,prirep,state,node,unassigned.reason") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.service.port":
        return prefix + "; ps -ef | grep '[e]lasticsearch'; ss -tlnp | grep -E \" :$es_http_port|:$es_http_port|:$es_transport_port\""
    if metric_id == "local.elasticsearch.heap.gc":
        return prefix + "; " + _es_curl("/_cat/nodes?v&h=name,heap.percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'; if test -n \"$es_gc_log\"; then tail -n 200 \"$es_gc_log\" | grep -Ei 'Pause|Full|OutOfMemory|heap'; else printf '%s\\n' INSPECT_ELASTICSEARCH_GC_LOG_NOT_FOUND; fi"
    if metric_id == "local.elasticsearch.thread_pool.rejected":
        return prefix + "; " + _es_curl("/_cat/thread_pool/search,write?v&h=node_name,name,active,queue,rejected,completed") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.cluster.settings":
        return prefix + "; " + _es_curl("/_cluster/settings?flat_settings=true&pretty") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.discovery.config":
        return prefix + "; if test -z \"$es_conf\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_CONFIG_NOT_FOUND; else printf 'INSPECT_ELASTICSEARCH_CONF=%s\\n' \"$es_conf\"; grep -E 'discovery.seed_hosts|cluster.initial_master_nodes|network.host|node.name' \"$es_conf\"; fi"
    if metric_id == "local.elasticsearch.indices.health":
        return prefix + "; " + _es_curl("/_cat/indices?v&h=health,index,pri,rep,docs.count,store.size&s=store.size:desc") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.slowlog.key_evidence":
        return prefix + "; if test -z \"$es_log_dir\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_LOG_NOT_FOUND; else ls -1 \"$es_log_dir\"/*slowlog* 2>/dev/null; tail -n 100 \"$es_log_dir\"/*slowlog* 2>/dev/null; fi"
    if metric_id == "local.elasticsearch.security.accounts":
        status = " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
        return prefix + "; " + _es_curl("/_security/user?pretty") + status + "; " + _es_curl("/_security/role?pretty") + status
    if metric_id == "local.elasticsearch.certificate.validity":
        return prefix + "; if test -z \"$es_cert\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_CERT_NOT_FOUND; else openssl x509 -in \"$es_cert\" -noout -dates -checkend 2592000; fi"
    if metric_id == "local.elasticsearch.snapshot.repository":
        repos = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_snapshot_repo")) or ""
        repo = repos.split()[0] if repos else ""
        status = " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
        verify = f"curl -k -sS --connect-timeout 3 --max-time 10 $es_auth -X POST \"$es_endpoint/{repo}/_verify?pretty\"{status}"
        return prefix + f"; if test -z \"$es_endpoint\" || test -z \"{repos}\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_SNAPSHOT_NOT_FOUND; else " + _es_curl("/_snapshot/_all?pretty") + status + "; " + verify + "; fi"
    if metric_id == "local.elasticsearch.system.parameters":
        return prefix + "; printf 'ES_MAX_MAP_COUNT=%s\\n' \"$(cat /proc/sys/vm/max_map_count 2>/dev/null)\"; free -m; if test -n \"$es_pid\" && test -r \"/proc/$es_pid/limits\"; then printf 'ES_ULIMIT_NOFILE=%s\\n' \"$(sed -nE 's/^Max open files[[:space:]]+([0-9]+).*/\\1/p' \"/proc/$es_pid/limits\" | head -n 1)\"; printf 'ES_ULIMIT_NPROC=%s\\n' \"$(sed -nE 's/^Max processes[[:space:]]+([0-9]+).*/\\1/p' \"/proc/$es_pid/limits\" | head -n 1)\"; printf 'ES_ULIMIT_MEMLOCK=%s\\n' \"$(sed -nE 's/^Max locked memory[[:space:]]+([^[:space:]]+).*/\\1/p' \"/proc/$es_pid/limits\" | head -n 1)\"; else printf 'ES_ULIMIT_NOFILE=\\nES_ULIMIT_NPROC=\\nES_ULIMIT_MEMLOCK=\\n'; fi"
    if metric_id == "local.elasticsearch.process.present":
        raise CommandConfigError("Elasticsearch 进程指标使用静态命令")
    raise CommandConfigError(f"未注册的 Elasticsearch 动态指标命令: {metric_id}")


def _nginx_discovery_prefix(profile: Dict[str, Any], *, include_dump: bool) -> str:
    """Discover one running Nginx instance and resolve its paths.

    The process command line is authoritative.  Config candidates in
    inspect.conf are only used when the process does not provide a value (or
    the discovered file is absent).  All inserted candidate values have
    passed the strict path/port validator above.
    """
    bins = _nginx_shell_words(_nginx_candidates(profile, "nginx_bin"))
    confs = _nginx_shell_words(_nginx_candidates(profile, "nginx_conf"))
    errors = _nginx_shell_words(_nginx_candidates(profile, "nginx_error_log"))
    accesses = _nginx_shell_words(_nginx_candidates(profile, "nginx_access_log"))
    # An empty candidate list must remain valid shell syntax.  ':' is only a
    # harmless loop item and is never accepted by the -x/-f checks.
    bins_loop = bins or ":"
    confs_loop = confs or ":"
    errors_loop = errors or ":"
    accesses_loop = accesses or ":"
    parts = [
        # Use the same self-match-safe expression as the process metric.
        "master_line=$(pgrep -fa '[n]ginx: master process' | head -n 1)",
        "nginx_bin=$(printf '%s\\n' \"$master_line\" | sed -nE 's/.*nginx: master process[[:space:]]+([^[:space:]]+).*/\\1/p')",
        "nginx_conf=$(printf '%s\\n' \"$master_line\" | sed -nE 's/.*[[:space:]]-c[[:space:]]*=?[[:space:]]*([^[:space:]]+).*/\\1/p')",
        "nginx_error_log=$(printf '%s\\n' \"$master_line\" | sed -nE 's/.*[[:space:]]-e[[:space:]]*=?[[:space:]]*([^[:space:]]+).*/\\1/p')",
        "if test -n \"$nginx_bin\" && ! test -x \"$nginx_bin\"; then nginx_bin=''; fi",
        f"if test -z \"$nginx_bin\"; then for p in {bins_loop}; do if test -x \"$p\"; then nginx_bin=\"$p\"; break; fi; done; fi",
        f"if test -z \"$nginx_conf\" || ! test -f \"$nginx_conf\"; then for p in {confs_loop}; do if test -f \"$p\"; then nginx_conf=\"$p\"; break; fi; done; fi",
        f"if test -z \"$nginx_error_log\" && test -n \"$nginx_conf\"; then nginx_error_log=$(sed -nE 's/^[[:space:]]*error_log[[:space:]]+([^[:space:];]+).*/\\1/p' \"$nginx_conf\" | head -n 1); fi",
        "nginx_prefix=$(printf '%s\\n' \"$nginx_conf\" | sed -nE 's#/conf/[^/]+$##p')",
        "case \"$nginx_error_log\" in /*) ;; '') ;; *) if test -n \"$nginx_prefix\"; then nginx_error_log=\"$nginx_prefix/$nginx_error_log\"; fi ;; esac",
        f"if test -z \"$nginx_error_log\" || ! test -f \"$nginx_error_log\"; then for p in {errors_loop}; do if test -f \"$p\"; then nginx_error_log=\"$p\"; break; fi; done; fi",
    ]
    if include_dump:
        parts += [
            "nginx_dump=''",
            "if test -n \"$nginx_bin\" && test -n \"$nginx_conf\"; then if test -n \"$nginx_error_log\"; then nginx_dump=$(\"$nginx_bin\" -T -e \"$nginx_error_log\" -c \"$nginx_conf\" 2>&1); else nginx_dump=$(\"$nginx_bin\" -T -c \"$nginx_conf\" 2>&1); fi; fi",
            "nginx_access_log=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*access_log[[:space:]]+([^[:space:];]+).*/\\1/p' | head -n 1)",
            "case \"$nginx_access_log\" in /*) ;; '') ;; *) if test -n \"$nginx_prefix\"; then nginx_access_log=\"$nginx_prefix/$nginx_access_log\"; fi ;; esac",
            f"if test -z \"$nginx_access_log\" || ! test -f \"$nginx_access_log\"; then for p in {accesses_loop}; do if test -f \"$p\"; then nginx_access_log=\"$p\"; break; fi; done; fi",
        ]
    return "; ".join(parts)


def _build_nginx_metric_command(metric_id: str, profile: Dict[str, Any]) -> str:
    """Build a per-metric Nginx command with process-first discovery."""
    if metric_id == "local.nginx.config.valid":
        error_candidates = _nginx_candidates(profile, "nginx_error_log")
        candidate_note = " ".join(f"-e {item}" for item in error_candidates) or "none"
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + f"; : 'inspect.conf nginx_error_log candidates: {candidate_note}'; if test -z \"$nginx_bin\" || test -z \"$nginx_conf\"; then printf '%s\\n' INSPECT_NGINX_CONFIG_NOT_FOUND; elif test -n \"$nginx_error_log\"; then \"$nginx_bin\" -t -e \"$nginx_error_log\" -c \"$nginx_conf\"; else \"$nginx_bin\" -t -c \"$nginx_conf\"; fi"
        )
    if metric_id == "local.nginx.version":
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + "; if test -z \"$master_line\" || test -z \"$nginx_bin\"; then printf '%s\\n' INSPECT_NGINX_RUNNING_NOT_FOUND; else \"$nginx_bin\" -v 2>&1; fi"
        )
    if metric_id == "local.nginx.port.listening":
        ports = _nginx_shell_words(_nginx_candidates(profile, "nginx_port"))
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + f"; nginx_ports=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*listen[[:space:]]+[^;]*:([0-9]+)[^;]*;/\\1/p; s/^[[:space:]]*listen[[:space:]]+([0-9]+)[^;]*;/\\1/p'); if test -z \"$nginx_ports\"; then nginx_ports='{ports}'; fi; if test -z \"$nginx_ports\"; then printf '%s\\n' INSPECT_NGINX_PORT_NOT_FOUND; else for port in $nginx_ports; do ss -tlnp | grep :$port; curl -sS -I --connect-timeout 3 \"http://127.0.0.1:$port/\" | head -n 1; done; fi"
        )
    if metric_id == "local.nginx.error_log.key_evidence":
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + "; if test -z \"$nginx_error_log\"; then printf '%s\\n' INSPECT_NGINX_ERROR_LOG_NOT_FOUND; else printf '%s\\n' \"$nginx_error_log\"; tail -n 1000 \"$nginx_error_log\" | egrep -i 'emerg|alert|crit|error|permission denied|bind\\(|connect\\(\\) failed|upstream timed out' | tail -n 20; fi"
        )
    if metric_id == "local.nginx.connections.status":
        ports = _nginx_shell_words(_nginx_candidates(profile, "nginx_port"))
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + f"; nginx_ports=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*listen[[:space:]]+[^;]*:([0-9]+)[^;]*;/\\1/p; s/^[[:space:]]*listen[[:space:]]+([0-9]+)[^;]*;/\\1/p'); if test -z \"$nginx_ports\"; then nginx_ports='{ports}'; fi; if test -z \"$nginx_ports\"; then printf '%s\\n' INSPECT_NGINX_PORT_NOT_FOUND; else for port in $nginx_ports; do curl -sS --connect-timeout 3 \"http://127.0.0.1:$port/nginx_status\"; done; fi"
        )
    if metric_id == "local.nginx.access_log.status_codes":
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + "; if test -z \"$nginx_access_log\"; then printf '%s\\n' INSPECT_NGINX_ACCESS_LOG_NOT_FOUND; else printf '%s\\n' \"$nginx_access_log\"; tail -n 1000 \"$nginx_access_log\" | grep -E ' [1-5][0-9][0-9] '; fi"
        )
    if metric_id in {"local.nginx.config.baseline", "local.nginx.security.baseline"}:
        patterns = (
            "worker_processes|worker_rlimit_nofile|worker_connections|use epoll|multi_accept|keepalive_timeout|client_max_body_size|limit_req|limit_conn"
            if metric_id.endswith("config.baseline")
            else "server_tokens|autoindex|X-Frame-Options|X-Content-Type-Options|Content-Security-Policy|request_method"
        )
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + f"; if test -z \"$nginx_conf\"; then printf '%s\\n' INSPECT_NGINX_CONFIG_NOT_FOUND; else printf '%s\\n' \"$nginx_conf\"; grep -E '{patterns}' \"$nginx_conf\"; fi"
        )
    raise CommandConfigError(f"未注册的 Nginx 动态指标命令: {metric_id}")


def _keepalived_discovery_prefix(profile: Dict[str, Any], *, include_log: bool = False) -> str:
    """Discover Keepalived's running binary/config before using fallbacks."""
    bins = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_bin"))
    confs = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_conf"))
    logs = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_log"))
    bins_loop = bins or ":"
    confs_loop = confs or ":"
    logs_loop = logs or ":"
    parts = [
        "process_line=$(pgrep -fa '(^|[[:space:]/])keepalived[[:space:]]' | head -n 1)",
        "keepalived_bin=$(printf '%s\\n' \"$process_line\" | sed -nE 's/^[0-9]+[[:space:]]+([^[:space:]]+).*/\\1/p')",
        "keepalived_conf=$(printf '%s\\n' \"$process_line\" | sed -nE 's/.*[[:space:]]-f[[:space:]]*=?[[:space:]]*([^[:space:]]+).*/\\1/p')",
        "if test -n \"$keepalived_bin\" && ! test -x \"$keepalived_bin\"; then keepalived_bin=''; fi",
        f"if test -z \"$keepalived_bin\"; then for p in {bins_loop}; do if test -x \"$p\"; then keepalived_bin=\"$p\"; break; fi; done; fi",
        "if test -n \"$keepalived_conf\" && ! test -f \"$keepalived_conf\"; then keepalived_conf=''; fi",
        f"if test -z \"$keepalived_conf\"; then for p in {confs_loop}; do if test -f \"$p\"; then keepalived_conf=\"$p\"; break; fi; done; fi",
    ]
    if include_log:
        parts += [
            f"keepalived_log=''; for p in {logs_loop}; do if test -f \"$p\"; then keepalived_log=\"$p\"; break; fi; done",
        ]
    return "; ".join(parts)


def _keepalived_config_prefix(profile: Dict[str, Any]) -> str:
    """Emit normalized config markers consumed by Keepalived parsers."""
    return (
        _keepalived_discovery_prefix(profile)
        + "; if test -z \"$keepalived_conf\"; then printf '%s\\n' INSPECT_KEEPALIVED_CONFIG_NOT_FOUND; else "
        + "printf 'INSPECT_KEEPALIVED_CONF=%s\\n' \"$keepalived_conf\"; "
        + "state=$(sed -nE 's/^[[:space:]]*state[[:space:]]+([A-Za-z]+).*/\\1/p' \"$keepalived_conf\" | head -n 1); printf 'CONFIG_STATE=%s\\n' \"$state\"; "
        + "awk '/virtual_ipaddress[[:space:]]*\\{/{inside=1;next} inside && /\\}/{inside=0;next} inside {gsub(/[;,]/,\"\",$1); if ($1 ~ /^[0-9A-Fa-f:.]+(\\/[0-9]+)?$/) print \"CONFIG_VIP=\" $1}' \"$keepalived_conf\"; fi"
    )


def _build_keepalived_metric_command(metric_id: str, profile: Dict[str, Any]) -> str:
    """Build a Keepalived command with process-first path discovery."""
    if metric_id == "local.keepalived.version":
        return (
            _keepalived_discovery_prefix(profile)
            + "; if test -z \"$process_line\" || test -z \"$keepalived_bin\"; then printf '%s\\n' INSPECT_KEEPALIVED_RUNNING_NOT_FOUND; else \"$keepalived_bin\" -v 2>&1; fi"
        )
    if metric_id == "local.keepalived.vip.bound":
        return _keepalived_config_prefix(profile) + "; if test -n \"$keepalived_conf\"; then ip -brief addr; fi"
    if metric_id == "local.keepalived.vip.access":
        vips = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_vip"))
        ports = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_port"))
        vip_extract = (
            "; keepalived_vips=''; if test -n \"$keepalived_conf\"; then "
            "keepalived_vips=$(sed -n '/virtual_ipaddress[[:space:]]*{/,/}/p' \"$keepalived_conf\" | "
            "grep -Eo '[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+(/[0-9]+)?' | head -n 1); fi; "
        )
        return (
            _keepalived_discovery_prefix(profile)
            + vip_extract
            + f"if test -z \"$keepalived_vips\"; then keepalived_vips='{vips}'; fi; keepalived_port='{ports}'; if test -z \"$keepalived_vips\" || test -z \"$keepalived_port\"; then printf '%s\\n' INSPECT_KEEPALIVED_VIP_NOT_FOUND; else for vip in $keepalived_vips; do vip=${{vip%%/*}}; for port in $keepalived_port; do printf 'CONFIG_ACCESS=%s:%s\\n' \"$vip\" \"$port\"; curl -sS -I --connect-timeout 3 \"http://$vip:$port/\" | head -n 1; done; done; fi"
        )
    if metric_id == "local.keepalived.config.baseline":
        return (
            _keepalived_discovery_prefix(profile)
            + "; if test -z \"$keepalived_conf\"; then printf '%s\\n' INSPECT_KEEPALIVED_CONFIG_NOT_FOUND; else printf '%s\\n' \"$keepalived_conf\"; grep -E 'state|interface|virtual_router_id|priority|advert_int|virtual_ipaddress|script|track_script' \"$keepalived_conf\"; fi"
        )
    if metric_id == "local.keepalived.healthcheck.script":
        return (
            _keepalived_discovery_prefix(profile)
            + "; if test -z \"$keepalived_conf\"; then printf '%s\\n' INSPECT_KEEPALIVED_CONFIG_NOT_FOUND; else script_path=$(awk '/^[[:space:]]*script[[:space:]]+/{if ($1==\"script\") {gsub(/[\";]/,\"\",$2); print $2; exit}}' \"$keepalived_conf\"); if test -z \"$script_path\"; then printf '%s\\n' INSPECT_KEEPALIVED_SCRIPT_NOT_FOUND; else printf 'CONFIG_SCRIPT=%s\\n' \"$script_path\"; ls -ld \"$script_path\" 2>/dev/null; if test -f \"$script_path\" && test -x \"$script_path\"; then printf '%s\\n' SCRIPT_EXECUTABLE=true; else printf '%s\\n' SCRIPT_EXECUTABLE=false; fi; fi; fi"
        )
    if metric_id == "local.keepalived.error_log.key_evidence":
        return (
            _keepalived_discovery_prefix(profile, include_log=True)
            + "; if test -z \"$keepalived_log\"; then printf '%s\\n' INSPECT_KEEPALIVED_LOG_NOT_FOUND; else printf 'INSPECT_KEEPALIVED_LOG=%s\\n' \"$keepalived_log\"; tail -n 1000 \"$keepalived_log\" | grep -Ei 'Entering MASTER|Entering BACKUP|Entering FAULT|script.*failed|VRRP'; fi"
        )
    if metric_id == "local.keepalived.capability.stability":
        return (
            _keepalived_discovery_prefix(profile, include_log=True)
            + "; if test -z \"$keepalived_bin\" || test -z \"$keepalived_log\"; then printf '%s\\n' INSPECT_KEEPALIVED_CAPABILITY_NOT_FOUND; else getcap \"$keepalived_bin\" 2>/dev/null; systemctl show keepalived-opt -p AmbientCapabilities -p CapabilityBoundingSet 2>/dev/null; printf 'INSPECT_KEEPALIVED_LOG=%s\\n' \"$keepalived_log\"; tail -n 50 \"$keepalived_log\"; fi"
        )
    raise CommandConfigError(f"未注册的 Keepalived 动态指标命令: {metric_id}")


def build_metric_command_specs(
    metrics: Optional[Sequence[Dict[str, Any]]] = None,
    profile: Optional[Dict[str, Any]] = None,
    module_ids: Optional[Sequence[str]] = None,
) -> List[CommandSpec]:
    """由指标注册表（metrics.py）+ TD §5.2 模板构造采集命令规格列表。

    - metrics=None 且未提供 profile → 默认只构造
      DEFAULT_COLLECTION_MODULE_IDS（当前为 linux_basic）的指标；
      module_ids 可显式选择额外模块，供未来中间件适配器接入。提供
      profile 时保留完整注册表兼容路径；完整注册表仍可通过
      default_registry().metric_definitions() 查询，不影响 --list-metrics；
    - profile：inspect.yml profiles 中单个产品的配置（TD §6.3）：
      提供 → 安全校验后替换占位符；缺失/未提供 → 对已显式选择的
      profile 指标构造 command=None + error_code=UNSUPPORTED_PROFILE；
      未选择的模块不会进入执行计划，也不会制造 UNKNOWN。
    - 超时取自 metrics.py 定义（timeout_sec：10s，日志类 15s，AE §7）；
    - 所需命令取自 probe.metric_required_commands（TD §5.2 数据源列）。
    """
    if metrics is None:
        if module_ids is not None:
            selected_modules = tuple(module_ids)
        elif profile is None:
            # The CLI's no-profile path is a generic Linux inspection.
            selected_modules = DEFAULT_COLLECTION_MODULE_IDS
        else:
            # Supplying a product profile is the explicit extension path for
            # middleware adapters; preserve the complete registered catalog
            # for callers that already have a profile.
            selected_modules = tuple(
                module.module_id for module in default_registry().iter_modules()
            )
        metrics = default_registry().metric_definitions(selected_modules)
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
        # Nginx is process-discovered.  Its command must still be emitted
        # when inspect.conf has no candidate values so that the target can
        # report UNKNOWN (rather than being mislabeled UNSUPPORTED_PROFILE).
        if (
            metric_id.startswith("local.nginx.")
            and metric_id != NGINX_PROCESS_METRIC
            and _is_runtime_nginx_profile(profile)
        ):
            command = _build_nginx_metric_command(metric_id, profile)
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_NGINX_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                )
            )
            continue
        if (
            metric_id.startswith("local.keepalived.")
            and metric_id != KEEPALIVED_PROCESS_METRIC
            and _is_runtime_keepalived_profile(profile)
        ):
            command = _build_keepalived_metric_command(metric_id, profile)
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_KEEPALIVED_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                )
            )
            continue
        if (
            metric_id.startswith("local.elasticsearch.")
            and metric_id != ELASTICSEARCH_PROCESS_METRIC
            and _is_runtime_elasticsearch_profile(profile)
        ):
            command = _build_elasticsearch_metric_command(metric_id, profile)
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_ELASTICSEARCH_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                )
            )
            continue
        if (
            metric_id.startswith("local.elasticsearch.")
            and metric_id != ELASTICSEARCH_PROCESS_METRIC
            and not _is_runtime_elasticsearch_profile(profile)
        ):
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=None,
                    timeout_sec=timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    error_code=ERROR_UNSUPPORTED_PROFILE,
                    error_message="未加载 inspect.conf Elasticsearch 运行配置；无法安全进行实例发现和路径兜底",
                )
            )
            continue
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
                    allowed_binaries=tuple(parse_binaries(command)),
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
        if spec.trusted_generated_shell:
            if not (
                spec.metric_id.startswith("local.nginx.")
                or spec.metric_id.startswith("local.keepalived.")
                or spec.metric_id.startswith("local.elasticsearch.")
            ):
                raise CommandNotAllowedError(
                    f"allow-list 拒绝：只有已注册中间件动态命令可使用内部 shell 变量: {spec.metric_id}"
                )
            if spec.metric_id.startswith("local.nginx."):
                unsafe_tokens = _NGINX_UNSAFE_GENERATED_TOKENS
            elif spec.metric_id.startswith("local.keepalived."):
                unsafe_tokens = _KEEPALIVED_UNSAFE_GENERATED_TOKENS
            else:
                unsafe_tokens = _ELASTICSEARCH_UNSAFE_GENERATED_TOKENS
            if "`" in spec.command or unsafe_tokens.search(spec.command):
                raise CommandNotAllowedError(
                    f"allow-list 拒绝：中间件动态命令含危险执行词: {spec.metric_id}"
                )
            # The command is generated entirely from fixed code plus values
            # validated by _nginx_candidates; do not run the ordinary `$` /
            # command-substitution rejection against this internal transport.
            found = list(spec.allowed_binaries)
            allowed = list(spec.allowed_binaries)
        else:
            allowed = spec.allowed_binaries or _allowed_binaries(spec.metric_id)
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
    nginx_whitelist: Tuple[str, ...] = ()
    keepalived_whitelist: Tuple[str, ...] = ()
    elasticsearch_whitelist: Tuple[str, ...] = ()


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parent.parent / _RUNTIME_DIR_NAME


def prepare_run(
    selection: Any,
    specs: Sequence[CommandSpec],
    runtime_dir: Optional[Path] = None,
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
) -> RunPlan:
    """allow-list 校验 → 生成 playbook 与 argv → RunPlan（不执行不连接）。

    selection：inventory.HostSelection 鸭子类型（.inventory_file/.hosts/
    .limit）；playbook 写入 runtime_dir（默认 <仓库根>/.runtime）。
    nginx_whitelist：Nginx 白名单 IP（白名单内未运行 → CRIT「未运行」；
    白名单外未运行 → 跳过该主机 Nginx 指标）。
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
        nginx_whitelist=tuple(nginx_whitelist or ()),
        keepalived_whitelist=tuple(keepalived_whitelist or ()),
        elasticsearch_whitelist=tuple(elasticsearch_whitelist or ()),
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
# 中间件按进程发现选择（nginx）：未运行主机跳过 / 白名单内 CRIT 未运行
# --------------------------------------------------------------------------

NGINX_METRIC_PREFIX = "local.nginx."
NGINX_PROCESS_METRIC = "local.nginx.process.present"
KEEPALIVED_METRIC_PREFIX = "local.keepalived."
KEEPALIVED_PROCESS_METRIC = "local.keepalived.process.present"
ELASTICSEARCH_METRIC_PREFIX = "local.elasticsearch."
ELASTICSEARCH_PROCESS_METRIC = "local.elasticsearch.process.present"


def _nginx_process_present(metric_result: Dict[str, Any]) -> bool:
    """进程发现结果是否命中 Nginx（rc=0 且 stdout 非空 = pgrep 有匹配）。"""
    return (
        metric_result.get("error") is None
        and metric_result.get("rc") == 0
        and bool((metric_result.get("stdout") or "").strip())
    )


def select_nginx_metrics(
    metric_results: Sequence[Dict[str, Any]],
    *,
    host_ip: str,
    nginx_whitelist: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """按进程发现结果决定主机保留哪些 Nginx 指标。

    - 该主机无 Nginx 指标 → 原样返回；
    - 进程发现结果缺失/采集失败 → 原样返回（UNKNOWN+error 由 normalize 呈现）；
    - Nginx 运行中 → 原样返回（保留全部 Nginx 指标）；
    - Nginx 未运行：
        * 主机 IP 在 nginx 白名单 → 只保留 local.nginx.process.present
          （normalize 判定 CRIT「未运行」），其余 Nginx 指标丢弃；
        * 白名单外 → 丢弃全部 Nginx 指标（该主机不是 Nginx 节点，跳过）。
    """
    results = list(metric_results)
    nginx = [m for m in results if m["metric_id"].startswith(NGINX_METRIC_PREFIX)]
    if not nginx:
        return results
    process = next((m for m in nginx if m["metric_id"] == NGINX_PROCESS_METRIC), None)
    if process is None or process.get("error") is not None:
        return results
    if _nginx_process_present(process):
        return results
    other = [m for m in results if not m["metric_id"].startswith(NGINX_METRIC_PREFIX)]
    whitelist = set(nginx_whitelist or [])
    if str(host_ip) in whitelist:
        return other + [process]
    return other


def _keepalived_process_present(metric_result: Dict[str, Any]) -> bool:
    """进程发现结果是否命中 Keepalived。"""
    return (
        metric_result.get("error") is None
        and metric_result.get("rc") == 0
        and bool((metric_result.get("stdout") or "").strip())
    )


def select_keepalived_metrics(
    metric_results: Sequence[Dict[str, Any]],
    *,
    host_ip: str,
    keepalived_whitelist: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """按 Keepalived 进程发现结果跳过非 HA 主机或保留白名单 CRIT。"""
    results = list(metric_results)
    keepalived = [
        m for m in results if m["metric_id"].startswith(KEEPALIVED_METRIC_PREFIX)
    ]
    if not keepalived:
        return results
    process = next(
        (m for m in keepalived if m["metric_id"] == KEEPALIVED_PROCESS_METRIC), None
    )
    if process is None or process.get("error") is not None:
        return results
    if _keepalived_process_present(process):
        return results
    other = [
        m for m in results if not m["metric_id"].startswith(KEEPALIVED_METRIC_PREFIX)
    ]
    if str(host_ip) in set(keepalived_whitelist or ()):
        return other + [process]
    return other


def select_elasticsearch_metrics(
    metric_results: Sequence[Dict[str, Any]],
    *,
    host_ip: str,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Skip hosts without ES, or retain only a whitelist CRIT process result."""
    results = list(metric_results)
    elasticsearch = [
        m for m in results if m["metric_id"].startswith(ELASTICSEARCH_METRIC_PREFIX)
    ]
    if not elasticsearch:
        return results
    process = next(
        (m for m in elasticsearch if m["metric_id"] == ELASTICSEARCH_PROCESS_METRIC), None
    )
    if process is None or process.get("error") is not None:
        return results
    if (
        process.get("error") is None
        and process.get("rc") == 0
        and bool((process.get("stdout") or "").strip())
    ):
        return results
    other = [
        m for m in results if not m["metric_id"].startswith(ELASTICSEARCH_METRIC_PREFIX)
    ]
    if str(host_ip) in set(elasticsearch_whitelist or ()):
        return other + [process]
    return other


# --------------------------------------------------------------------------
# 执行（本任务仅 fixture 模式；真实执行 G0 前置）
# --------------------------------------------------------------------------


def _fixture_metric_result(
    host_dir: Path, spec: CommandSpec, probe_matrix: Dict[str, bool]
) -> Dict[str, Any]:
    def with_command(result: Dict[str, Any]) -> Dict[str, Any]:
        result["command"] = spec.command or ""
        return result

    if spec.command is None and spec.error_code == ERROR_UNSUPPORTED_PROFILE:
        return with_command(classify_metric_result(
            spec.metric_id,
            None,
            "",
            "",
            spec.required_commands,
            probe_matrix,
            preset_error={"code": ERROR_UNSUPPORTED_PROFILE, "message": spec.error_message or ""},
        ))
    out_file = host_dir / f"{spec.metric_id}.out"
    if (host_dir / f"{spec.metric_id}.timeout").exists():
        return with_command(classify_metric_result(
            spec.metric_id, TIMEOUT_RC, "", "", spec.required_commands, probe_matrix
        ))
    if not out_file.is_file():
        return with_command(classify_metric_result(
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
        ))
    stdout = _read_fixture_text(out_file)
    stderr = (
        _read_fixture_text(host_dir / f"{spec.metric_id}.stderr")
        if (host_dir / f"{spec.metric_id}.stderr").is_file()
        else ""
    )
    rc = _read_fixture_rc(host_dir / f"{spec.metric_id}.rc")
    if rc is None:
        rc = 0
    return with_command(classify_metric_result(
        spec.metric_id, rc, stdout, stderr, spec.required_commands, probe_matrix
    ))


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
        metric_results = select_nginx_metrics(
            metric_results,
            host_ip=str(host.ip),
            nginx_whitelist=plan.nginx_whitelist,
        )
        metric_results = select_keepalived_metrics(
            metric_results,
            host_ip=str(host.ip),
            keepalived_whitelist=plan.keepalived_whitelist,
        )
        metric_results = select_elasticsearch_metrics(
            metric_results,
            host_ip=str(host.ip),
            elasticsearch_whitelist=plan.elasticsearch_whitelist,
        )
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


def _callback_error_for_failed_connection() -> Dict[str, str]:
    """分类无 rc 的 Ansible 连接前置失败（例如 sshpass/host-key 检查）。"""
    return _error(ERROR_CONNECTION_FAILED, "Ansible 连接前置检查失败（无业务结论）")


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
            remote_user = _validate_remote_user(os.environ.get(REMOTE_USER_ENV_VAR))
            # A user-provided inventory is allowed to carry ansible_user,
            # ansible_password, SSH key, or SSH-config based authentication.
            # The parser never reads those values; Ansible receives the
            # original inventory file and resolves them itself.  Generated
            # -H inventories still require the legacy explicit user path.
            if remote_user is None and plan.selection_kind != "inventory":
                raise RealExecutionError(
                    "remote real execution requires an explicit remote user or "
                    "inventory-configured authentication",
                    category="remote_user_missing",
                    check=(
                        "configure inventory/hosts.ini (or -i inventory) with "
                        "Ansible auth, or set only INSPECT_REMOTE_USER"
                    ),
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
        env["ANSIBLE_HOST_KEY_CHECKING"] = ANSIBLE_HOST_KEY_CHECKING
        env["ANSIBLE_SSH_COMMON_ARGS"] = ANSIBLE_SSH_COMMON_ARGS
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
                # Ansible may report password/host-key/sshpass preflight failures
                # as failed=true without rc or unreachable=true.  Do not turn
                # that control-plane failure into a misleading PROBE_FAILED.
                if raw.get("failed") and raw.get("rc") is None:
                    state["host_error"] = _callback_error_for_failed_connection()
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
                metric_result = classify_metric_result(
                    metric_id,
                    rc,
                    _callback_text(raw.get("stdout")),
                    _callback_text(raw.get("stderr")),
                    spec.required_commands,
                    state["probe_matrix"],
                )
                metric_result["command"] = spec.command or ""
                state["metrics"][metric_id] = metric_result

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
                metric_result = classify_metric_result(
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
                metric_result["command"] = spec.command or ""
                metrics.append(metric_result)
                continue
            if spec.metric_id in state["metrics"]:
                metrics.append(state["metrics"][spec.metric_id])
                continue
            metric_result = classify_metric_result(
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
            metric_result["command"] = spec.command or ""
            metrics.append(metric_result)
        metrics = select_nginx_metrics(
            metrics,
            host_ip=str(state["host"].ip),
            nginx_whitelist=plan.nginx_whitelist,
        )
        metrics = select_keepalived_metrics(
            metrics,
            host_ip=str(state["host"].ip),
            keepalived_whitelist=plan.keepalived_whitelist,
        )
        metrics = select_elasticsearch_metrics(
            metrics,
            host_ip=str(state["host"].ip),
            elasticsearch_whitelist=plan.elasticsearch_whitelist,
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
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """prepare_run + execute_plan 便捷入口（cli 编排挂接点）。"""
    plan = prepare_run(
        selection,
        specs,
        runtime_dir=runtime_dir,
        nginx_whitelist=nginx_whitelist,
        keepalived_whitelist=keepalived_whitelist,
        elasticsearch_whitelist=elasticsearch_whitelist,
    )
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
    "RealExecutionError",
    "FIXTURE_ENV_VAR",
    "HOST_TIMEOUT_SEC",
    "LOG_METRIC_TIMEOUT_SEC",
    "METRIC_ERROR_STATUS",
    "METRIC_TIMEOUT_SEC",
    "NGINX_METRIC_PREFIX",
    "NGINX_PROCESS_METRIC",
    "KEEPALIVED_METRIC_PREFIX",
    "KEEPALIVED_PROCESS_METRIC",
    "ELASTICSEARCH_METRIC_PREFIX",
    "ELASTICSEARCH_PROCESS_METRIC",
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
    "select_nginx_metrics",
    "select_keepalived_metrics",
    "select_elasticsearch_metrics",
    "validate_command_specs",
]
