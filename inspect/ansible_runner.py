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
import shlex
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
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
# Remote execution is host-scoped: one Ansible process/playbook per host,
# coordinated by controller threads.  ``parallel`` is the worker count, not
# Ansible's multi-host serial setting.  A playbook itself always targets one
# host and therefore remains ``serial: 1``.
DEFAULT_PARALLEL_HOSTS = 10
MIN_PARALLEL_HOSTS = 1
MAX_PARALLEL_HOSTS = 10
MIN_COMMAND_TIMEOUT_SEC = 1
MAX_COMMAND_TIMEOUT_SEC = 60

# GNU coreutils timeout 的默认退出码（命令超时 → 分类为 TIMEOUT）
TIMEOUT_RC = 124
# curl 的操作超时退出码；外层 GNU timeout 通常会将其转换为 124，但保留
# 28 兼容 curl 在恰好达到 --max-time 时先自行退出的情况。
CURL_TIMEOUT_RC = 28

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
# API 密码只在一次性生成的 raw shell command 中使用；允许现场常见密码字符，
# 拒绝控制字符与 inspect.conf 的候选分隔符；事实源/报表规范化阶段会统一脱敏。
_SAFE_ELASTICSEARCH_CREDENTIAL = re.compile(r"^[^\x00-\x1f\x7f|]+$")

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
    # Some generated middleware commands need private environment values.  The
    # value is rendered into a short, controller-side Jinja lookup prefix by
    # generate_playbook().  Keeping the task as ``raw`` is intentional:
    # ansible.builtin.shell/script modules can require Python on the managed
    # host, while raw only needs the target's SSH shell.
    module: str = "ansible.builtin.raw"
    task_environment: Dict[str, str] = field(default_factory=dict)
    # Optional, independently validated report command.  Never infer this
    # from the collector command template: dynamic middleware commands remain
    # null unless a concrete context supplies an explicit value.
    replay_command: Optional[str] = None


# 进程发现不能只用 pgrep -fa：Ansible raw 在某些 SSH/TTY 组合下会把
# 远端命令文本回显到进程列表，命令文本中的 ``local.nginx`` 等字符串
# 会造成自匹配。这里同时锚定 ps 的 comm 列和 args 列，只认真实进程。
_NGINX_PROCESS_COMMAND = (
    "ps -eo pid=,comm=,args= | grep -E "
    "'^[[:space:]]*[0-9]+[[:space:]]+nginx[[:space:]]+nginx: (master|worker) process'"
)
_KEEPALIVED_PROCESS_COMMAND = (
    "ps -eo pid=,comm=,args= | grep -E "
    "'^[[:space:]]*[0-9]+[[:space:]]+keepalived[[:space:]]'"
)
_ELASTICSEARCH_PROCESS_COMMAND = (
    "ps -eo pid=,comm=,args= | grep -E "
    "'^[[:space:]]*[0-9]+[[:space:]]+"
    "(java[[:space:]].*org\\.elasticsearch\\.bootstrap\\.Elasticsearch|"
    "elasticsearch[[:space:]])'"
)
_ELASTICSEARCH_DISCOVERY_COMMAND = (
    "ps -eo pid=,comm=,args= | grep -E "
    "'^[[:space:]]*[0-9]+[[:space:]]+"
    "(java[[:space:]].*org\\.elasticsearch\\.(bootstrap\\.Elasticsearch|launcher\\.CliToolLauncher)|"
    "elasticsearch[[:space:]])'"
)


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
        # ps 的 comm 列必须是 nginx，避免匹配 inspect/Ansible 命令自身。
        "command": _NGINX_PROCESS_COMMAND,
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
            "netstat -lntp | grep ':{nginx_port}'; "
            "curl -sS -I --connect-timeout 3 http://{nginx_listener_host}:{nginx_port}/ | head -n 1"
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
    "local.nginx.http.reachability": {
        "command": "curl -sS --connect-timeout 3 -I http://{nginx_listener_host}:{nginx_port}/ | head -n 1",
        "profile_keys": ("nginx_port",),
        "become": False,
        "anchor": "DOCX:安徽农金Nginx、Keepalived运维巡检手册v1.0.docx:TABLE6-R4",
    },
    "local.nginx.fd.process.limits": {
        "command": "ps -eo pid=,comm=,args= | grep -E '^[[:space:]]*[0-9]+[[:space:]]+nginx[[:space:]]+nginx: master process'",
        "profile_keys": (),
        "become": False,
        "anchor": "DOCX:安徽农金Nginx、Keepalived运维巡检手册v1.0.docx:TABLE7-R7",
    },
    # ---- Keepalived 中间件（keepalived-p0-v1） ----
    "local.keepalived.process.present": {
        "command": _KEEPALIVED_PROCESS_COMMAND,
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
        "command": "curl -sS -I http://{keepalived_vip}:{keepalived_port}/",
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
        "command": _ELASTICSEARCH_PROCESS_COMMAND,
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

# Additional middleware adapters use the exact, redacted manual command as a
# static collector template.  Their module-specific defaults live in
# inspect.conf for report provenance and future dynamic discovery; the first
# implementation deliberately keeps collection independent of a guessed path.
_ADDITIONAL_COMMANDS = {
    "local.keepalived.vip.present": "ip -brief addr; grep -E 'virtual_ipaddress|interface' <KEEPALIVED_CONF>",
    "local.keepalived.vrrp.role": "grep -E 'state|priority|virtual_router_id|interface' <KEEPALIVED_CONF>",
    "local.keepalived.health_check.status": "grep -E 'track_script|script' <KEEPALIVED_CONF>; test -x <HEALTHCHECK_SCRIPT>",
    "local.kafka.broker.health": "test -r <KAFKA_CONF>; pgrep -fa '[k]afka.Kafka' | grep -v 'INSPECT_MIDDLEWARE_NOT_RUNNING='; ss -tlnp | grep ':9093'",
    "local.kafka.controller.health": "$kafka_bin_dir/zookeeper-shell.sh \"$kafka_zookeeper_root\" get \"$kafka_zookeeper_path/controller\"",
    "local.kafka.broker.registration": "BROKER_ID=$(awk -F= '$1 ~ /^[[:space:]]*broker[.]id[[:space:]]*$/ {gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", $2); print $2; exit}' \"$kafka_conf\"); \"$kafka_bin_dir/zookeeper-shell.sh\" \"$kafka_zookeeper_root\" get \"$kafka_zookeeper_path/brokers/ids/${BROKER_ID}\"",
    "local.kafka.under_replicated_partitions": "out=$(\"$kafka_topics\" --bootstrap-server \"$kafka_bootstrap\" --command-config \"$kafka_ssl_config\" --describe); rc=$?; if [ \"$rc\" -ne 0 ]; then printf 'KAFKA_COMMAND_FAILED=true\\n'; elif [ -n \"$out\" ]; then printf 'KAFKA_FULL_TOPIC_DESCRIBE=true\\n%s\\n' \"$out\"; else printf 'KAFKA_NO_UNDER_REPLICATED=true\\n'; fi",
    "local.kafka.under_min_isr": "out=$(\"$kafka_topics\" --bootstrap-server \"$kafka_bootstrap\" --command-config \"$kafka_ssl_config\" --describe); rc=$?; if [ \"$rc\" -ne 0 ]; then printf 'KAFKA_COMMAND_FAILED=true\\n'; elif [ -n \"$out\" ]; then printf 'KAFKA_FULL_TOPIC_DESCRIBE=true\\n%s\\n' \"$out\"; else printf 'KAFKA_NO_UNDER_MIN_ISR=true\\n'; fi",
    "local.kafka.topic.replica_distribution": "out=$(\"$kafka_topics\" --bootstrap-server \"$kafka_bootstrap\" --command-config \"$kafka_ssl_config\" --describe); rc=$?; if [ \"$rc\" -ne 0 ]; then printf 'KAFKA_COMMAND_FAILED=true\\n'; elif [ -n \"$out\" ]; then printf '%s\\n' \"$out\"; else printf 'KAFKA_NO_TOPICS=true\\n'; fi",
    "local.kafka.consumer.lag": "out=$(\"$kafka_consumer_groups\" --bootstrap-server \"$kafka_bootstrap\" --command-config \"$kafka_ssl_config\" --describe --all-groups); rc=$?; if [ \"$rc\" -ne 0 ]; then printf 'KAFKA_COMMAND_FAILED=true\\n'; elif [ -n \"$out\" ]; then printf '%s\\n' \"$out\"; else printf 'KAFKA_NO_CONSUMER_GROUPS=true\\n'; fi",
    "local.kafka.error_log": "grep -R -iE 'ERROR|FATAL|OutOfMemory|NotLeader|UnderReplicated|IOException|Session expired' <KAFKA_LOG> 2>/dev/null | tail -30; grep_rc=${PIPESTATUS[0]}; if [ \"$grep_rc\" -eq 1 ]; then printf 'KAFKA_LOG_OK=true\\n'; elif [ \"$grep_rc\" -gt 1 ]; then printf 'KAFKA_LOG_PARSE_FAILED=true\\n'; fi",
    "local.kafka.config.baseline": "grep -E '^(listeners|advertised.listeners|inter.broker.listener.name|log.dirs|zookeeper.connect|default.replication.factor|min.insync.replicas|unclean.leader.election.enable|auto.create.topics.enable)' <KAFKA_CONF>",
    "local.kafka.ssl.certificate": "cert=$(find <KAFKA_CERTS> -type f \\( -name '*.crt' -o -name '*.pem' \\) -print 2>/dev/null | head -1); if [ -z \"$cert\" ]; then printf 'KAFKA_SSL_CERT_NOT_FOUND=true\\n'; elif openssl x509 -in \"$cert\" -noout -dates -checkend 2592000 >/dev/null 2>&1; then printf 'KAFKA_SSL_CERT_OK=true\\n'; else printf 'KAFKA_SSL_CERT_FAILED=true\\n'; fi; ls -l <KAFKA_CERTS>/*.p12 2>/dev/null",
    "local.kafka.system.parameters": "KAFKA_PID=$(pgrep -f '[k]afka\\.Kafka' | head -1); nofile=$(awk '$1==\"Max\" && $2==\"open\" {print $4; exit}' \"/proc/$KAFKA_PID/limits\"); nproc=$(awk '$1==\"Max\" && $2==\"processes\" {print $4; exit}' \"/proc/$KAFKA_PID/limits\"); swap_used=$(free -b | awk '/^Swap:/ {print $3}'); swappiness=$(cat /proc/sys/vm/swappiness); printf 'nofile=%s\\nnproc=%s\\nswap_used=%s\\nswappiness=%s\\n' \"$nofile\" \"$nproc\" \"$swap_used\" \"$swappiness\"",
    "local.zookeeper.node.health": "echo ruok | nc -w 3 127.0.0.1 <ZOOKEEPER_CLIENT_PORT>; echo stat | nc -w 3 127.0.0.1 <ZOOKEEPER_CLIENT_PORT> | egrep 'Mode|Node count|Connections'",
    "local.zookeeper.ports.health": "ss -tlnp | grep -E ':<ZOOKEEPER_CLIENT_PORT>|:<ZOOKEEPER_PEER_PORT>|:<ZOOKEEPER_ELECTION_PORT>'",
    "local.zookeeper.error_log": "grep -R -iE 'ERROR|FATAL|OutOfMemory|NotLeader|IOException|Session expired' <ZOOKEEPER_LOG> 2>/dev/null | tail -30; grep_rc=${PIPESTATUS[0]}; if [ \"$grep_rc\" -eq 1 ]; then printf 'ZK_LOG_OK=true\\n'; elif [ \"$grep_rc\" -gt 1 ]; then printf 'ZK_LOG_PARSE_FAILED=true\\n'; fi",
    "local.zookeeper.mntr.health": "echo mntr | nc -w 3 127.0.0.1 <ZOOKEEPER_CLIENT_PORT> | egrep 'zk_avg_latency|zk_max_latency|zk_outstanding_requests|zk_num_alive_connections|zk_znode_count|zk_watch_count'",
    "local.zookeeper.data.retention": "du -sh <ZOOKEEPER_DATA> <ZOOKEEPER_DATALOG> 2>/dev/null; ls -lt <ZOOKEEPER_DATA>/version-2 2>/dev/null | head -10; ls -lt <ZOOKEEPER_DATALOG>/version-2 2>/dev/null | head -10",
    "local.zookeeper.config.baseline": "grep -E '^(dataDir|dataLogDir|clientPort|server\\.|autopurge|4lw.commands.whitelist|admin.enableServer|standaloneEnabled|reconfigEnabled)' <ZOOKEEPER_CONF>; cat <ZOOKEEPER_DATA>/myid",
    "local.mysql.service.health": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -e \"SELECT 1;\"; test -r <MYSQL_CONF>; ls -ld <MYSQL_LOG>",
    "local.mysql.login.version": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -p -e \"SELECT @@version,@@hostname,@@port;\"",
    "local.mysql.role.gtid": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -p -e \"SELECT @@server_id,@@gtid_mode,@@enforce_gtid_consistency,@@read_only,@@super_read_only;\"",
    "local.mysql.replica.threads": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -p -e \"SHOW REPLICA STATUS\\G\" | egrep 'Replica_IO_Running|Replica_SQL_Running|Last_IO_Errno|Last_SQL_Errno'",
    "local.mysql.replication.lag": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -p -e \"SHOW REPLICA STATUS\\G\" | egrep 'Seconds_Behind_Source|Read_Source_Log_Pos|Exec_Source_Log_Pos'",
    "local.mysql.connection.pressure": "<MYSQL_BIN> --socket=<MYSQL_SOCKET> -u<USER> -p -e \"SHOW GLOBAL STATUS LIKE 'Threads_connected'; SHOW GLOBAL STATUS LIKE 'Max_used_connections'; SHOW VARIABLES LIKE 'max_connections';\"",
    "local.nacos.service.health": "test -x <NACOS_BIN>; pgrep -fa 'com.alibaba.nacos|nacos.home|<NACOS_HOME>'; tail -n 50 <NACOS_LOG>/start.out",
    "local.nacos.core_ports.health": "ss -tlnp | egrep ':8848|:9848|:9849|:7848'",
    "local.nacos.http.health": "curl -sS --connect-timeout 3 http://127.0.0.1:8848/nacos/actuator/health",
    "local.nacos.cluster.nodes": "curl -sS 'http://127.0.0.1:8848/nacos/v2/core/cluster/node/list?accessToken=<TOKEN>'",
    "local.nacos.mysql.connectivity": "grep -E '^(spring.sql.init.platform|db.num|db.url.0|db.user.0)' <NACOS_CONF>; nc -vz <MYSQL_HOST> 3306",
    "local.nacos.error_log": "grep -R -iE 'ERROR|FATAL|OutOfMemory|No DataSource|SQLException|Connection refused|raft|failed' <NACOS_LOG> | tail -80",
    "local.rabbitmq.service.health": "test -r <RABBITMQ_CONF>; test -x <RABBITMQ_BIN>; pgrep -fa 'beam.smp|rabbitmq-server'; systemctl is-active rabbitmq; tail -n 50 <RABBITMQ_LOG>/rabbit.log",
    "local.rabbitmq.node.health": "<RABBITMQ_DIAGNOSTICS> ping; <RABBITMQ_DIAGNOSTICS> status",
    "local.rabbitmq.cluster.nodes": "<RABBITMQCTL> cluster_status",
    "local.rabbitmq.alarm.partition": "<RABBITMQ_DIAGNOSTICS> check_local_alarms; <RABBITMQCTL> cluster_status | egrep -i 'alarms|partitions|running_nodes'",
    "local.rabbitmq.queue.backlog": "<RABBITMQCTL> list_queues -p / name state messages messages_ready messages_unacknowledged consumers",
    "local.rabbitmq.connection.pressure": "<RABBITMQCTL> list_connections state channels send_pend; <RABBITMQCTL> list_channels messages_unacknowledged",
    "local.redis.service.health": "test -x <REDIS_BIN>; test -r <REDIS_CONF>; pgrep -fa 'redis-server.*(6379|16379|7000)'; systemctl is-active redis; ls -ld <REDIS_LOG>",
    "local.redis.ping.version": "<REDIS_CLI> -h 127.0.0.1 -p <PORT> PING; <REDIS_CLI> -h 127.0.0.1 -p <PORT> INFO server",
    "local.redis.replication.health": "<REDIS_CLI> -p <PORT> INFO replication",
    "local.redis.sentinel.health": "<REDIS_CLI> -p 26379 INFO sentinel; <REDIS_CLI> -p 26379 SENTINEL masters",
    "local.redis.cluster.health": "<REDIS_CLI> -p 7000 CLUSTER INFO; <REDIS_CLI> -p 7000 CLUSTER NODES",
    "local.redis.persistence.health": "<REDIS_CLI> -p <PORT> INFO persistence; <REDIS_CLI> -p <PORT> CONFIG GET appendonly appendfsync dir",
    "local.rocketmq.namesrv.health": "test -d <ROCKETMQ_CONF>; pgrep -fa 'NamesrvStartup|mqnamesrv'; tail -n 50 <ROCKETMQ_LOG>/rocketmqlogs/namesrv.log 2>/dev/null; tail -n 50 <ROCKETMQ_HOME>/logs/rocketmqlogs/namesrv.log",
    "local.rocketmq.broker.health": "test -d <ROCKETMQ_CONF>; pgrep -fa 'BrokerStartup|mqbroker'; tail -n 50 <ROCKETMQ_LOG>/rocketmqlogs/broker.log 2>/dev/null; tail -n 50 <ROCKETMQ_HOME>/logs/rocketmqlogs/broker.log",
    "local.rocketmq.core_ports.health": "ss -tlnp | egrep ':9876|:9877|:10911|:10912'",
    "local.rocketmq.cluster.registration": "<MQADMIN> clusterList -n <NAMESRV_ADDR>",
    "local.rocketmq.controller.sync_set": "<MQADMIN> getControllerMetaData -a <CONTROLLER_ADDR>; <MQADMIN> getSyncStateSet -a <CONTROLLER_ADDR> -b <BROKER>",
    "local.rocketmq.consumer.lag": "<MQADMIN> consumerProgress -n <NAMESRV_ADDR>; <MQADMIN> statsAll -n <NAMESRV_ADDR>",
    "local.tomcat.service.health": "test -x <TOMCAT_BIN>; ps -ef | grep '[o]rg.apache.catalina.startup.Bootstrap'",
    "local.tomcat.http.health": "ss -lntp | egrep '(:8080|:8443|:8005)\\b'",
    "local.tomcat.access_log.errors": "tail -200 <TOMCAT_LOG>/catalina.out | egrep -i 'Server startup in|SEVERE|Exception|OutOfMemoryError|Address already in use'",
    "local.tomcat.jvm.memory": "PID=$(pgrep -f 'org.apache.catalina.startup.Bootstrap' | head -1); ps -o pid,rss,vsz,%mem,etime,cmd -p \"$PID\"; free -h",
    "local.tomcat.thread_pool.pressure": "PID=$(pgrep -f 'org.apache.catalina.startup.Bootstrap' | head -1); echo fd=$(ls /proc/$PID/fd 2>/dev/null | wc -l); echo threads=$(ls /proc/$PID/task 2>/dev/null | wc -l); cat /proc/$PID/limits 2>/dev/null | egrep 'Max open files|Max processes'",
    "local.tomcat.security.baseline": "egrep -n '(<Server port=|<Connector|autoDeploy=|deployOnStartup=|server=)' <TOMCAT_CONF>",
}
for _middleware_metric_id, _middleware_command in _ADDITIONAL_COMMANDS.items():
    _COMMAND_TEMPLATES[_middleware_metric_id] = {
        "command": _middleware_command,
        "profile_keys": (),
        "become": False,
        "anchor": "DOCX:middleware-v1.0:P0/P1",
    }

_ADDITIONAL_PLACEHOLDER_KEYS = {
    "local.keepalived.vip.present": {"<KEEPALIVED_CONF>": ("keepalived_conf", "keepalived.conf")},
    "local.keepalived.vrrp.role": {"<KEEPALIVED_CONF>": ("keepalived_conf", "keepalived.conf")},
    "local.keepalived.health_check.status": {
        "<KEEPALIVED_CONF>": ("keepalived_conf", "keepalived.conf"),
        "<HEALTHCHECK_SCRIPT>": "keepalived_healthcheck_script",
    },
    "local.kafka.broker.health": {"<KAFKA_LOG>": "kafka_log", "<KAFKA_CONF>": "kafka_conf"},
    "local.kafka.controller.health": {
        "<KAFKA_CONF>": "kafka_conf",
    },
    "local.kafka.broker.registration": {
        "<KAFKA_CONF>": "kafka_conf",
    },
    "local.kafka.under_replicated_partitions": {},
    "local.kafka.under_min_isr": {},
    "local.kafka.topic.replica_distribution": {},
    "local.kafka.consumer.lag": {},
    "local.kafka.error_log": {"<KAFKA_LOG>": "kafka_log"},
    "local.kafka.config.baseline": {"<KAFKA_CONF>": "kafka_conf"},
    "local.kafka.ssl.certificate": {"<KAFKA_CERTS>": ("kafka_conf", "certs")},
    "local.kafka.system.parameters": {},
    "local.zookeeper.node.health": {"<ZOOKEEPER_CLIENT_PORT>": "zookeeper_client_port"},
    "local.zookeeper.ports.health": {
        "<ZOOKEEPER_CLIENT_PORT>": "zookeeper_client_port",
        "<ZOOKEEPER_PEER_PORT>": "zookeeper_peer_port",
        "<ZOOKEEPER_ELECTION_PORT>": "zookeeper_election_port",
    },
    "local.zookeeper.error_log": {"<ZOOKEEPER_LOG>": "zookeeper_log"},
    "local.zookeeper.mntr.health": {"<ZOOKEEPER_CLIENT_PORT>": "zookeeper_client_port"},
    "local.zookeeper.data.retention": {
        "<ZOOKEEPER_DATA>": "zookeeper_data",
        "<ZOOKEEPER_DATALOG>": "zookeeper_datalog",
    },
    "local.zookeeper.config.baseline": {
        "<ZOOKEEPER_CONF>": "zookeeper_conf",
        "<ZOOKEEPER_DATA>": "zookeeper_data",
    },
    "local.mysql.service.health": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket",
        "<MYSQL_CONF>": "mysql_conf", "<MYSQL_LOG>": "mysql_log",
        "<USER>": "mysql_user",
    },
    "local.mysql.login.version": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket", "<USER>": "mysql_user",
    },
    "local.mysql.role.gtid": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket", "<USER>": "mysql_user",
    },
    "local.mysql.replica.threads": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket", "<USER>": "mysql_user",
    },
    "local.mysql.replication.lag": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket", "<USER>": "mysql_user",
    },
    "local.mysql.connection.pressure": {
        "<MYSQL_BIN>": "mysql_bin", "<MYSQL_SOCKET>": "mysql_socket", "<USER>": "mysql_user",
    },
    "local.nacos.service.health": {
        "<NACOS_BIN>": "nacos_bin", "<NACOS_HOME>": "nacos_home", "<NACOS_LOG>": "nacos_log",
    },
    "local.nacos.cluster.nodes": {"<TOKEN>": "nacos_token"},
    "local.nacos.mysql.connectivity": {"<NACOS_CONF>": "nacos_conf", "<MYSQL_HOST>": "mysql_host"},
    "local.nacos.error_log": {"<NACOS_LOG>": "nacos_log"},
    "local.rabbitmq.service.health": {
        "<RABBITMQ_CONF>": "rabbitmq_conf", "<RABBITMQ_BIN>": "rabbitmq_bin", "<RABBITMQ_LOG>": "rabbitmq_log",
    },
    "local.rabbitmq.node.health": {"<RABBITMQ_DIAGNOSTICS>": ("rabbitmq_bin", "rabbitmq-diagnostics")},
    "local.rabbitmq.cluster.nodes": {"<RABBITMQCTL>": ("rabbitmq_bin", "rabbitmqctl")},
    "local.rabbitmq.alarm.partition": {
        "<RABBITMQ_DIAGNOSTICS>": ("rabbitmq_bin", "rabbitmq-diagnostics"),
        "<RABBITMQCTL>": ("rabbitmq_bin", "rabbitmqctl"),
    },
    "local.rabbitmq.queue.backlog": {"<RABBITMQCTL>": ("rabbitmq_bin", "rabbitmqctl")},
    "local.rabbitmq.connection.pressure": {"<RABBITMQCTL>": ("rabbitmq_bin", "rabbitmqctl")},
    "local.redis.service.health": {
        "<REDIS_BIN>": "redis_bin", "<REDIS_CONF>": ("redis_conf", "redis.conf"), "<REDIS_LOG>": "redis_log",
    },
    "local.redis.ping.version": {"<REDIS_CLI>": ("redis_bin", "redis-cli"), "<PORT>": "redis_port"},
    "local.redis.replication.health": {"<REDIS_CLI>": ("redis_bin", "redis-cli"), "<PORT>": "redis_port"},
    "local.redis.sentinel.health": {"<REDIS_CLI>": ("redis_bin", "redis-cli")},
    "local.redis.cluster.health": {"<REDIS_CLI>": ("redis_bin", "redis-cli")},
    "local.redis.persistence.health": {"<REDIS_CLI>": ("redis_bin", "redis-cli"), "<PORT>": "redis_port"},
    "local.rocketmq.namesrv.health": {"<ROCKETMQ_CONF>": "rocketmq_conf", "<ROCKETMQ_LOG>": "rocketmq_log", "<ROCKETMQ_HOME>": "rocketmq_home"},
    "local.rocketmq.broker.health": {"<ROCKETMQ_CONF>": "rocketmq_conf", "<ROCKETMQ_LOG>": "rocketmq_log", "<ROCKETMQ_HOME>": "rocketmq_home"},
    "local.rocketmq.cluster.registration": {"<MQADMIN>": ("rocketmq_bin", "mqadmin"), "<NAMESRV_ADDR>": "rocketmq_namesrv_addr"},
    "local.rocketmq.controller.sync_set": {
        "<MQADMIN>": ("rocketmq_bin", "mqadmin"), "<CONTROLLER_ADDR>": "rocketmq_controller_addr", "<BROKER>": "rocketmq_broker",
    },
    "local.rocketmq.consumer.lag": {"<MQADMIN>": ("rocketmq_bin", "mqadmin"), "<NAMESRV_ADDR>": "rocketmq_namesrv_addr"},
    "local.tomcat.service.health": {"<TOMCAT_BIN>": ("tomcat_bin", "catalina.sh")},
    "local.tomcat.access_log.errors": {"<TOMCAT_LOG>": "tomcat_log"},
    "local.tomcat.security.baseline": {"<TOMCAT_CONF>": ("tomcat_conf", "server.xml")},
}

_ADDITIONAL_PLACEHOLDER_DEFAULTS = {
    "keepalived_conf": "/opt/keepalived/conf/keepalived.conf",
    "keepalived_healthcheck_script": "/etc/keepalived/check.sh",
    "kafka_zookeeper_conf": "/opt/zookeeper/conf/zoo.cfg",
    "zookeeper_bin": "/opt/redis/bin/redis-server",
    "zookeeper_conf": "/opt/zookeeper/conf/zoo.cfg",
    "zookeeper_log": "/opt/zookeeper/logs",
    "zookeeper_data": "/opt/zookeeper/data",
    "zookeeper_datalog": "/opt/zookeeper/datalog",
    "zookeeper_client_port": "2181",
    "zookeeper_peer_port": "2888",
    "zookeeper_election_port": "3888",
    "kafka_log": "/opt/kafka/logs/",
    "kafka_zookeeper_connect": "127.0.0.1:2181",
    "kafka_bootstrap": "127.0.0.1:9093",
    "kafka_ssl_config": "/opt/kafka/conf/client-ssl.properties",
    "mysql_socket": "/opt/mysql/tmp/mysql.sock",
    "mysql_bin": "/opt/mysql/bin/mysql",
    "mysql_conf": "/opt/mysql/conf/my.cnf",
    "mysql_log": "/opt/mysql/logs",
    "mysql_user": "root",
    "mysql_host": "127.0.0.1",
    "nacos_token": "CHANGE_ME",
    "nacos_home": "/opt/nacos",
    "nacos_bin": "/opt/nacos/bin/startup.sh",
    "nacos_conf": "/opt/nacos/conf/application.properties",
    "nacos_log": "/opt/nacos/logs",
    "rabbitmq_bin": "/opt/rabbitmq/sbin/rabbitmq-server",
    "rabbitmq_log": "/opt/rabbitmq/logs",
    "redis_bin": "/opt/redis/bin/redis-server",
    "redis_conf": "/opt/redis/conf",
    "redis_log": "/opt/redis/logs",
    "redis_port": "6379",
    "rocketmq_namesrv_addr": "127.0.0.1:9876",
    "rocketmq_controller_addr": "127.0.0.1:9877",
    "rocketmq_broker": "broker-a",
    "rocketmq_log": "/opt/rabbitmq/logs",
    "tomcat_bin": "/opt/tomcat/bin",
    "tomcat_conf": "/opt/tomcat/conf",
    "tomcat_log": "/opt/tomcat/logs",
}
_SAFE_ADDITIONAL_VALUE = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")
_ADDITIONAL_GENERATED_ALLOWED_BINARIES = (
    "awk", "bash", "cat", "cut", "curl", "echo", "egrep", "find", "free", "grep", "head",
    "ip", "jcmd", "jstat", "kafka-consumer-groups.sh", "kafka-topics.sh", "ls", "mqadmin", "mysql", "nc",
    "openssl",
    "pgrep", "ps", "rabbitmq-diagnostics", "rabbitmqctl", "redis-cli", "sed",
    "ss", "su", "systemctl", "tail", "test", "unlink", "wc", "zookeeper-shell.sh", "zkServer.sh",
)
_ADDITIONAL_UNSAFE_GENERATED_TOKENS = re.compile(
    r"\b(?:rm|rmdir|mkfs|dd|shutdown|reboot|poweroff|sudo|ssh|scp|wget|"
    r"python|perl|ruby|php|eval|exec|source|chmod|chown|mount|umount)\b"
)


def _additional_profile_values(profile: Dict[str, Any], key: str) -> List[str]:
    raw = profile[key] if key in profile else _ADDITIONAL_PLACEHOLDER_DEFAULTS[key]
    values = raw if isinstance(raw, list) else [raw]
    if not values:
        values = [_ADDITIONAL_PLACEHOLDER_DEFAULTS[key]]
    normalized = [str(value) for value in values]
    if any(
        not value or not _SAFE_ADDITIONAL_VALUE.fullmatch(value)
        for value in normalized
    ):
        raise CommandConfigError(f"additional middleware profile {key} 非法")
    return normalized


def _additional_profile_value(profile: Dict[str, Any], key: str) -> str:
    return _additional_profile_values(profile, key)[0]


def _kafka_runtime_prefix(profile: Dict[str, Any]) -> str:
    """Resolve Kafka tools and endpoints on the target, with conf fallbacks."""
    kafka_conf = _additional_profile_values(profile, "kafka_conf")
    kafka_bins = _additional_profile_values(profile, "kafka_bin")
    kafka_ssl_configs = _additional_profile_values(profile, "kafka_ssl_config")
    zk_fallback = _additional_profile_value(profile, "kafka_zookeeper_connect")
    bootstrap_fallback = _additional_profile_value(profile, "kafka_bootstrap")
    conf_args = " ".join(shlex.quote(value) for value in kafka_conf)
    bin_args = " ".join(shlex.quote(value) for value in kafka_bins)
    ssl_config_args = " ".join(shlex.quote(value) for value in kafka_ssl_configs)
    fallback_conf = shlex.quote(kafka_conf[0])
    fallback_bin_dir = shlex.quote(kafka_bins[0].rsplit("/", 1)[0])
    fallback_ssl_config = shlex.quote(kafka_ssl_configs[0])
    zk_fallback_q = shlex.quote(zk_fallback)
    bootstrap_fallback_q = shlex.quote(bootstrap_fallback)
    return (
        f"kafka_conf={fallback_conf}; "
        f"for kafka_candidate in {conf_args}; do "
        "if [ -r \"$kafka_candidate\" ]; then kafka_conf=\"$kafka_candidate\"; break; fi; "
        "done; "
        f"kafka_bin_dir={fallback_bin_dir}; "
        f"for kafka_candidate in {bin_args}; do "
        "kafka_candidate_dir=\"${kafka_candidate%/*}\"; "
        "if [ -x \"$kafka_candidate_dir/zookeeper-shell.sh\" ] || "
        "[ -x \"$kafka_candidate_dir/kafka-topics.sh\" ] || "
        "[ -x \"$kafka_candidate_dir/kafka-consumer-groups.sh\" ]; then "
        "kafka_bin_dir=\"$kafka_candidate_dir\"; break; fi; "
        "done; "
        "kafka_zookeeper_connect=$(awk -F= '$1 ~ /^[[:space:]]*zookeeper[.]connect[[:space:]]*$/ "
        "{gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", $2); print $2; exit}' \"$kafka_conf\"); "
        f"if [ -z \"$kafka_zookeeper_connect\" ]; then kafka_zookeeper_connect={zk_fallback_q}; fi; "
        "kafka_zookeeper_root=\"${kafka_zookeeper_connect%%/*}\"; "
        "kafka_zookeeper_chroot=; kafka_zookeeper_path=; "
        "case \"$kafka_zookeeper_connect\" in */*) kafka_zookeeper_chroot=\"${kafka_zookeeper_connect#*/}\"; "
        "kafka_zookeeper_path=\"/${kafka_zookeeper_chroot#/}\";; esac; "
        "kafka_bootstrap=$(awk -F= '$1 ~ /^[[:space:]]*advertised[.]listeners[[:space:]]*$/ "
        "{gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", $2); split($2, a, \",\"); "
        "sub(/^[^:]+:\\/\\//, \"\", a[1]); print a[1]; exit}' \"$kafka_conf\"); "
        "if [ -z \"$kafka_bootstrap\" ]; then "
        "kafka_bootstrap=$(awk -F= '$1 ~ /^[[:space:]]*listeners[[:space:]]*$/ "
        "{gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", $2); split($2, a, \",\"); "
        "sub(/^[^:]+:\\/\\//, \"\", a[1]); print a[1]; exit}' \"$kafka_conf\"); fi; "
        f"if [ -z \"$kafka_bootstrap\" ]; then kafka_bootstrap={bootstrap_fallback_q}; fi; "
        "kafka_ssl_config=; kafka_ssl_config_temp=; "
        f"for kafka_ssl_candidate in {ssl_config_args}; do "
        "if [ -r \"$kafka_ssl_candidate\" ]; then "
        "kafka_ssl_missing=0; for kafka_ssl_path in $(awk -F= '/^[[:space:]]*ssl\\.(keystore|truststore)\\.location[[:space:]]*=/ "
        "{gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", $2); print $2}' \"$kafka_ssl_candidate\"); do "
        "if [ ! -r \"$kafka_ssl_path\" ]; then kafka_ssl_missing=1; fi; done; "
        "if [ \"$kafka_ssl_missing\" -eq 0 ]; then kafka_ssl_config=\"$kafka_ssl_candidate\"; break; fi; fi; done; "
        "if [ -z \"$kafka_ssl_config\" ] && [ -r \"$kafka_conf\" ]; then "
        "kafka_ssl_config_temp=$(mktemp \"${TMPDIR:-/tmp}/inspect-kafka-client.XXXXXX\") || kafka_ssl_config_temp=; "
        "if [ -n \"$kafka_ssl_config_temp\" ]; then "
        "{ printf '%s\\n' 'security.protocol=SSL' 'ssl.endpoint.identification.algorithm='; "
        "awk -F= '/^(ssl\\.(keystore|truststore)\\.(type|location|password)|ssl\\.key\\.password|ssl\\.(protocol|enabled\\.protocols))=/ {print}' \"$kafka_conf\"; "
        "} > \"$kafka_ssl_config_temp\" || { unlink \"$kafka_ssl_config_temp\"; kafka_ssl_config_temp=; }; "
        "kafka_ssl_config=\"$kafka_ssl_config_temp\"; fi; fi; "
        f"if [ -z \"$kafka_ssl_config\" ]; then kafka_ssl_config={fallback_ssl_config}; fi; "
        "trap 'if [ -n \"$kafka_ssl_config_temp\" ]; then unlink \"$kafka_ssl_config_temp\"; fi' EXIT HUP INT TERM; "
        "kafka_topics=\"$kafka_bin_dir/kafka-topics.sh\"; "
        "kafka_consumer_groups=\"$kafka_bin_dir/kafka-consumer-groups.sh\""
    )


def _derive_additional_path(value: str, suffix: Optional[str]) -> str:
    """Derive a sibling tool/file from a configured absolute path safely."""
    if not suffix:
        return value
    if not value.startswith("/") or not _SAFE_ADDITIONAL_VALUE.fullmatch(value):
        raise CommandConfigError(f"additional middleware path 非法: {value!r}")
    base = value.rstrip("/")
    sibling_tools = {
        "kafka-topics.sh", "zkServer.sh", "zookeeper-shell.sh",
        "rabbitmq-diagnostics", "rabbitmqctl", "redis-cli", "mqadmin",
    }
    if suffix in sibling_tools:
        parent = base.rsplit("/", 1)[0]
        return f"{parent}/{suffix}"
    if value.endswith("/") or "." not in base.rsplit("/", 1)[-1]:
        return f"{base}/{suffix}"
    parent = base.rsplit("/", 1)[0]
    return f"{parent}/{suffix}"


def _build_additional_command(metric_id: str, profile: Dict[str, Any]) -> str:
    command = _COMMAND_TEMPLATES[metric_id]["command"]
    for placeholder, spec in _ADDITIONAL_PLACEHOLDER_KEYS.get(metric_id, {}).items():
        if isinstance(spec, tuple):
            key, suffix = spec
        else:
            key, suffix = spec, None
        value = _additional_profile_value(profile, key)
        command = command.replace(placeholder, _derive_additional_path(value, suffix))
    if metric_id.startswith("local.kafka."):
        command = f"{_kafka_runtime_prefix(profile)}; {command}"
    typed_prefixes = (
        "local.kafka.", "local.mysql.", "local.nacos.", "local.rabbitmq.",
        "local.redis.", "local.rocketmq.", "local.tomcat.", "local.zookeeper.",
    )
    typed_keepalived = {
        "local.keepalived.vip.present",
        "local.keepalived.vrrp.role",
        "local.keepalived.health_check.status",
    }
    if metric_id.startswith(typed_prefixes) or metric_id in typed_keepalived:
        module_id = metric_id.split(".", 2)[1]
        gate_specs = {
            "keepalived": (r"keepalived", "keepalived_conf"),
            "kafka": (r"[k]afka\.Kafka", "kafka_conf"),
            "mysql": (r"mysqld", "mysql_conf"),
            "nacos": (r"com\.alibaba\.nacos|nacos", "nacos_home"),
            "rabbitmq": (r"beam\.smp|rabbitmq-server", "rabbitmq_conf"),
            "redis": (r"redis-server", "redis_conf"),
            "rocketmq": (r"NamesrvStartup|BrokerStartup|mqnamesrv|mqbroker", "rocketmq_conf"),
            "tomcat": (r"org\.apache\.catalina\.startup\.Bootstrap", "tomcat_conf"),
            "zookeeper": (r"QuorumPeerMain|org\.apache\.zookeeper\.server\.quorum\.QuorumPeerMain", "zookeeper_conf"),
        }
        pattern, config_key = gate_specs[module_id]
        # Resolve the module's configured path to select/validate the gate,
        # but do not require that path to appear in a process command line.
        # Java/native service managers commonly keep the config in an
        # environment or unit file rather than argv.
        _additional_profile_value(profile, config_key)
        gate = (
            f"if ! pgrep -fa '{pattern}' >/dev/null 2>&1; then printf '%s\\n' "
            f"INSPECT_MIDDLEWARE_NOT_RUNNING={module_id}; exit 0; fi"
        )
        command = f"{gate}; {command}"
    return command


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
    if key in ("nginx_conf", "nginx_log", "nginx_error_log", "nginx_access_log"):
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
    "pgrep", "ps", "sed", "head", "tail", "grep", "netstat", "ss", "curl", "ls",
    "openssl",
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
        elif key in {"nginx_bin", "nginx_conf", "nginx_log", "nginx_error_log", "nginx_access_log"}:
            result.append(_validate_profile_value(key, item))
        else:
            raise CommandConfigError(f"不支持的 Nginx 候选参数: {key}")
    return result


def _nginx_shell_words(values: Sequence[str]) -> str:
    """Build a safe shell word list from values already profile-validated."""
    return " ".join(values)


def _nginx_path_candidates(
    profile: Dict[str, Any], key: str, filename: Optional[str] = None
) -> List[str]:
    """Expand directory defaults such as ``/opt/nginx/conf/`` safely.

    The user-facing inspect.conf value remains unchanged.  Commands that need
    a concrete file receive the conventional filename only when the configured
    value is a directory; an explicit file path is preserved verbatim.
    """
    values = _nginx_candidates(profile, key)
    if not filename:
        return values
    expanded: List[str] = []
    for value in values:
        if value.endswith("/"):
            expanded.append(value.rstrip("/") + "/" + filename)
        else:
            expanded.append(value)
    return expanded


def _is_runtime_nginx_profile(profile: Dict[str, Any]) -> bool:
    """Identify the list-shaped profile loaded from inspect.conf.

    The scalar-shaped legacy profile remains supported for fixture/test callers
    and old library integrations.  The CLI always supplies the list-shaped
    inspect.conf result, including an all-empty result when no fallbacks are
    configured, so production execution always uses auto-discovery.
    """
    keys = (
        "nginx_bin", "nginx_conf", "nginx_log", "nginx_error_log", "nginx_access_log",
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


def _keepalived_path_candidates(
    profile: Dict[str, Any], key: str, filename: Optional[str] = None
) -> List[str]:
    """Expand configured Keepalived directories to concrete files."""
    values = _keepalived_candidates(profile, key)
    if not filename:
        return values
    return [
        value.rstrip("/") + "/" + filename if value.endswith("/") else value
        for value in values
    ]


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
            "elasticsearch_auth_file", "elasticsearch_cacert", "elasticsearch_cert",
        }:
            if not _SAFE_PATH.fullmatch(item):
                raise CommandConfigError(f"inspect.conf {key} 路径非法: {item!r}")
        elif key == "elasticsearch_endpoint":
            if not re.fullmatch(r"https?://[A-Za-z0-9_.:%+\-/]+", item):
                raise CommandConfigError(f"inspect.conf {key} URL 非法: {item!r}")
        elif key in {"elasticsearch_system_user", "elasticsearch_snapshot_repo"}:
            if not re.fullmatch(r"[A-Za-z0-9_.@+-]+", item):
                raise CommandConfigError(f"inspect.conf {key} 值非法: {item!r}")
        elif key in {"elasticsearch_api_user", "elasticsearch_api_password"}:
            if not _SAFE_ELASTICSEARCH_CREDENTIAL.fullmatch(item):
                raise CommandConfigError(
                    f"inspect.conf {key} 含控制字符或候选分隔符: {item!r}"
                )
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
        "elasticsearch_api_user", "elasticsearch_api_password",
        "elasticsearch_cacert", "elasticsearch_cert", "elasticsearch_snapshot_repo",
    )
    return any(key in profile for key in keys) and all(
        key not in profile or isinstance(profile.get(key), list) for key in keys
    )


def _elasticsearch_discovery_prefix(profile: Dict[str, Any]) -> str:
    """Discover ES paths and HTTP listener from the running JVM/config first.

    The HTTP host is deliberately taken from the effective Elasticsearch
    configuration, not from the controller inventory and not from a fixed
    loopback address.  ``http.host``/``http.bind_host`` take precedence over
    ``network.bind_host``/``network.host``.  Wildcard and Elasticsearch
    special hosts (for example ``0.0.0.0`` and ``_site_``) are not usable curl
    destinations, so they produce an empty endpoint and an explicit UNKNOWN
    parse result rather than silently probing 127.0.0.1.
    """
    bins = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_bin")) or ":"
    confs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_conf")) or ":"
    logs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_log")) or ":"
    gc_logs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_gc_log")) or ":"
    certs = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_cert")) or ":"
    cacerts = _elasticsearch_shell_words(
        _elasticsearch_candidates(profile, "elasticsearch_cacert")
    ) or certs or ":"
    auths = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_auth_file")) or ":"
    endpoints = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_endpoint")) or ":"
    http_ports = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_http_port")) or "9200"
    transport_ports = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_transport_port")) or "9300"
    system_users = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_system_user")) or "es"
    return "; ".join([
        # The server JVM and the launcher do not carry the same arguments on
        # tar installations.  The server line is authoritative for process
        # presence/PID, while the launcher line commonly carries
        # -Des.path.home/-Des.path.conf.  Looking at only one line was the
        # reason real Kylin nodes produced a large block of false UNKNOWNs.
        f"es_process_line=$({_ELASTICSEARCH_PROCESS_COMMAND} | grep -E 'org\\.elasticsearch\\.(bootstrap\\.Elasticsearch|launcher\\.CliToolLauncher)' | grep -E 'bootstrap\\.Elasticsearch' | head -n 1)",
        f"es_path_line=$({_ELASTICSEARCH_DISCOVERY_COMMAND} | grep -E 'org\\.elasticsearch\\.(bootstrap\\.Elasticsearch|launcher\\.CliToolLauncher)' | grep -E -- '-Des\\.path\\.(home|conf)=' | head -n 1)",
        "if test -z \"$es_path_line\"; then es_path_line=\"$es_process_line\"; fi",
        "es_home=$(printf '%s\\n' \"$es_path_line\" | sed -nE 's/.*-Des.path.home=([^[:space:]]+).*/\\1/p')",
        "es_conf_dir=$(printf '%s\\n' \"$es_path_line\" | sed -nE 's/.*-Des.path.conf=([^[:space:]]+).*/\\1/p')",
        "es_bin=$(printf '%s\\n' \"$es_path_line\" | sed -nE 's/.*[[:space:]]([^[:space:]]*\\/bin\\/elasticsearch)([[:space:]]|$).*/\\1/p')",
        "if test -n \"$es_home\" && test -x \"$es_home/bin/elasticsearch\"; then es_bin=\"$es_home/bin/elasticsearch\"; fi",
        f"if test -z \"$es_bin\" || ! test -x \"$es_bin\"; then for p in {bins}; do if test -x \"$p\"; then es_bin=\"$p\"; break; fi; done; fi",
        "if test -z \"$es_conf_dir\" && test -n \"$es_home\"; then es_conf_dir=\"$es_home/config\"; fi",
        "es_conf=\"\"; if test -n \"$es_conf_dir\" && test -f \"$es_conf_dir/elasticsearch.yml\"; then es_conf=\"$es_conf_dir/elasticsearch.yml\"; fi",
        f"if test -z \"$es_conf\"; then for p in {confs}; do if test -f \"$p\"; then es_conf=\"$p\"; break; fi; done; fi",
        # ``ps -eo pid=`` right-aligns the PID with leading spaces.  Missing
        # that whitespace made /proc/$pid/limits look unavailable and turned
        # every real node's system-parameter metric into UNKNOWN.
        "es_pid=$(printf '%s\\n' \"$es_process_line\" | sed -nE 's/^[[:space:]]*([0-9]+).*/\\1/p')",
        "es_user=\"\"; if test -n \"$es_pid\"; then es_user=$(ps -o user= -p \"$es_pid\" | sed -n 's/[[:space:]]//gp'); fi",
        f"if test -z \"$es_user\"; then for p in {system_users}; do es_user=\"$p\"; break; done; fi",
        "es_log_dir=$(printf '%s\\n' \"$es_path_line\" | sed -nE 's/.*-Des.path.logs=([^[:space:]]+).*/\\1/p')",
        # Most Elasticsearch tar deployments configure path.logs/path.data
        # in elasticsearch.yml instead of JVM properties.  The effective
        # config is authoritative: do not prefer the home-directory fallback
        # when path.logs points elsewhere.
        "if test -z \"$es_log_dir\" && test -n \"$es_conf\"; then es_log_dir=$(sed -nE 's/^[[:space:]]*path.logs:[[:space:]]*([^#]+).*/\\1/p' \"$es_conf\" | tr -d '[\\\"]' | sed -E 's/[[:space:]]+$//' | head -n 1); fi",
        "if test -z \"$es_log_dir\" && test -n \"$es_home\"; then es_log_dir=\"$es_home/logs\"; fi",
        "es_log=\"\"; if test -n \"$es_log_dir\"; then for p in \"$es_log_dir\"/*; do if test -f \"$p\"; then es_log=\"$p\"; break; fi; done; fi",
        f"if test -z \"$es_log\"; then for p in {logs}; do if test -f \"$p\"; then es_log=\"$p\"; break; fi; done; fi",
        "es_gc_log=\"\"; if test -n \"$es_log_dir\"; then for p in \"$es_log_dir\"/gc.log*; do if test -f \"$p\"; then es_gc_log=\"$p\"; break; fi; done; fi",
        f"if test -z \"$es_gc_log\"; then for p in {gc_logs}; do if test -f \"$p\"; then es_gc_log=\"$p\"; break; fi; done; fi",
        "es_http_port=$(test -n \"$es_conf\" && sed -nE 's/^[[:space:]]*http.port:[[:space:]]*([0-9]+).*/\\1/p' \"$es_conf\" | head -n 1)",
        f"if test -z \"$es_http_port\"; then es_http_port={http_ports}; fi",
        "es_transport_port=$(test -n \"$es_conf\" && sed -nE 's/^[[:space:]]*transport.port:[[:space:]]*([0-9]+).*/\\1/p' \"$es_conf\" | head -n 1)",
        f"if test -z \"$es_transport_port\"; then es_transport_port={transport_ports}; fi",
        # Use the configured listener address.  Do not use a controller-side
        # inventory address and do not force 127.0.0.1: some deployments bind
        # only to their service IP.  Values such as 0.0.0.0/_site_ are
        # filtered because they are bind selectors, not connectable addresses.
        # Choose a connectable address by key precedence, not by the order in
        # which settings happen to appear in elasticsearch.yml.
        "es_listen_host=\"\"; if test -n \"$es_conf\"; then for host_key in http.host http.bind_host network.publish_host network.host; do candidate=$(sed -nE \"s/^[[:space:]]*$host_key:[[:space:]]*//p\" \"$es_conf\" | tr -d '[]\"' | tr ',' '\\n' | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+|[[:space:]]+$//g' | grep -Ev '^(_|0\\.0\\.0\\.0$|::|0:0:0:0:0:0:0:0$)' | head -n 1); if test -n \"$candidate\"; then es_listen_host=\"$candidate\"; break; fi; done; fi",
        # If the effective config binds to a wildcard, use the concrete
        # address reported by the local listener.  Never silently substitute
        # 127.0.0.1 or an inventory address.
        "if test -z \"$es_listen_host\" && command -v ss >/dev/null 2>&1; then es_listen_host=$(ss -H -ltn \"sport = :$es_http_port\" 2>/dev/null | sed -nE 's/^[[:space:]]*[A-Z]+[[:space:]]+[0-9]+[[:space:]]+[0-9]+[[:space:]]+([^[:space:]]+):[0-9]+.*/\\1/p' | sed -E 's/^\\[::ffff:(.*)\\]$/\\1/; s/^\\[(.*)\\]$/\\1/' | grep -Ev '^(0\\.0\\.0\\.0|\\*|::)$' | head -n 1); fi",
        "es_endpoint=\"\"; if test -n \"$es_listen_host\"; then case \"$es_listen_host\" in *:*) es_endpoint=\"https://[$es_listen_host]:$es_http_port\";; *) es_endpoint=\"https://$es_listen_host:$es_http_port\";; esac; fi",
        "if test -z \"$es_endpoint\"; then for p in " + endpoints + "; do if test -n \"$p\"; then es_endpoint=\"$p\"; break; fi; done; fi",
        "es_auth_file=\"\"; for p in " + auths + "; do if test -f \"$p\"; then es_auth_file=\"$p\"; break; fi; done",
        "es_cert=\"\"; if test -n \"$es_conf\"; then es_cert=$(grep -Eo '/[^[:space:]]+\\.(crt|pem)' \"$es_conf\" | head -n 1); fi",
        f"if test -z \"$es_cert\"; then for p in {certs}; do if test -f \"$p\"; then es_cert=\"$p\"; break; fi; done; fi",
        "es_cacert=\"$es_cert\"",
        f"if test -z \"$es_cacert\"; then for p in {cacerts}; do if test -f \"$p\"; then es_cacert=\"$p\"; break; fi; done; fi",
        # The API CA is also the HTTPS certificate evidence when the
        # dedicated validity candidate list is not configured separately.
        "if test -z \"$es_cert\" && test -n \"$es_cacert\"; then es_cert=\"$es_cacert\"; fi",
        "es_api_user=\"${INSPECT_ES_API_USER:-}\"; es_api_password=\"${INSPECT_ES_API_PASSWORD:-}\"",
        "es_curl_args=()",
        "if test -n \"$es_api_user\" && test -n \"$es_api_password\"; then es_curl_args+=(-u \"$es_api_user:$es_api_password\"); elif test -n \"$es_auth_file\"; then es_curl_args+=(--netrc-file \"$es_auth_file\"); fi",
        "if test -n \"$es_cacert\" && test -f \"$es_cacert\"; then es_curl_args+=(--cacert \"$es_cacert\"); else es_curl_args+=(-k); fi",
    ])


def _elasticsearch_task_environment(profile: Dict[str, Any]) -> Dict[str, str]:
    """Return private ES API credentials for the generated task environment."""
    users = _elasticsearch_candidates(profile, "elasticsearch_api_user")
    passwords = _elasticsearch_candidates(profile, "elasticsearch_api_password")
    if not users or not passwords:
        return {}
    if passwords[0].strip().upper() in {"CHANGE_ME", "REPLACE_ME", "请填写"}:
        return {}
    return {
        "INSPECT_ES_API_USER": users[0],
        "INSPECT_ES_API_PASSWORD": passwords[0],
    }


def _es_curl(path: str, options: str = "", *, timeout_sec: int = METRIC_TIMEOUT_SEC) -> str:
    """Build a curl call using task-local auth/TLS arrays, never literals."""
    extra = f" {options}" if options else ""
    return (
        f"curl -sS --connect-timeout {timeout_sec} --max-time {timeout_sec} "
        f"\"${{es_curl_args[@]}}\"{extra} \"$es_endpoint{path}\""
    )


def _build_elasticsearch_metric_command(
    metric_id: str, profile: Dict[str, Any], *, timeout_sec: int = METRIC_TIMEOUT_SEC
) -> str:
    prefix = _elasticsearch_discovery_prefix(profile)
    def api(path: str, options: str = "") -> str:
        return _es_curl(path, options, timeout_sec=timeout_sec)

    if metric_id == "local.elasticsearch.version":
        # Do not execute the Elasticsearch launcher for version discovery.
        # On some tar deployments the launcher starts a JVM and can block;
        # the authenticated root API already returns version.number and is
        # both faster and authoritative for the running service.
        return (
            prefix
            + "; if test -z \"$es_process_line\" || test -z \"$es_endpoint\"; then "
            + "printf '%s\\n' INSPECT_ELASTICSEARCH_RUNNING_NOT_FOUND; else "
            + api("/")
            + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'; fi"
        )
    if metric_id == "local.elasticsearch.cluster.health":
        return prefix + "; if test -z \"$es_endpoint\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_ENDPOINT_NOT_FOUND; else " + api("/_cluster/health?pretty") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'; fi"
    if metric_id == "local.elasticsearch.nodes.online":
        return prefix + "; " + api("/_cat/nodes?v&h=name,ip,node.role,master,heap.percent,cpu,load_1m,disk.used_percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.cpu":
        return prefix + "; " + api("/_cat/nodes?v&h=name,ip,cpu,load_1m,load_5m,load_15m") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.memory":
        return prefix + "; " + api("/_cat/nodes?v&h=name,heap.percent,ram.percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.nodes.disk":
        return prefix + "; " + api("/_cat/allocation?v") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.disk.watermark":
        return prefix + "; " + api("/_cluster/settings?include_defaults=true&filter_path=**.watermark*") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.shards.unassigned":
        return prefix + "; " + api("/_cat/shards?v&h=index,shard,prirep,state,node,unassigned.reason") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.service.port":
        # Query the configured HTTP/Transport ports directly.  The previous
        # broad grep could miss a valid LISTEN row on some ss output layouts;
        # use the portable full LISTEN listing instead.  The normalizer checks
        # the discovered expected ports against this listing, so unrelated
        # sockets cannot make the metric pass.
        return prefix + "; if test -n \"$es_process_line\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_PROCESS=true; else printf '%s\\n' INSPECT_ELASTICSEARCH_PROCESS=false; fi; printf 'INSPECT_ELASTICSEARCH_EXPECTED_PORTS=%s,%s\\n' \"${es_http_port:-9200}\" \"${es_transport_port:-9300}\"; printf '%s\\n' \"$es_process_line\"; ss -tlnp | grep -E '^LISTEN[[:space:]]'"
    if metric_id == "local.elasticsearch.heap.gc":
        return prefix + "; " + api("/_cat/nodes?v&h=name,heap.percent") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'; if test -n \"$es_gc_log\"; then tail -n 200 \"$es_gc_log\" | grep -Ei 'Pause|Full|OutOfMemory|heap'; else printf '%s\\n' INSPECT_ELASTICSEARCH_GC_LOG_NOT_FOUND; fi"
    if metric_id == "local.elasticsearch.thread_pool.rejected":
        return prefix + "; " + api("/_cat/thread_pool/search,write?v&h=node_name,name,active,queue,rejected,completed") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.cluster.settings":
        return prefix + "; " + api("/_cluster/settings?flat_settings=true&pretty") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.discovery.config":
        return prefix + "; if test -z \"$es_conf\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_CONFIG_NOT_FOUND; else printf 'INSPECT_ELASTICSEARCH_CONF=%s\\n' \"$es_conf\"; grep -E 'discovery.seed_hosts|cluster.initial_master_nodes|network.host|node.name' \"$es_conf\"; fi"
    if metric_id == "local.elasticsearch.indices.health":
        return prefix + "; " + api("/_cat/indices?v&h=health,index,pri,rep,docs.count,store.size&s=store.size:desc") + " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
    if metric_id == "local.elasticsearch.slowlog.key_evidence":
        return prefix + "; if test -z \"$es_log_dir\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_LOG_NOT_FOUND; elif ls -1 \"$es_log_dir\"/*slowlog* >/dev/null 2>&1; then ls -1 \"$es_log_dir\"/*slowlog* 2>/dev/null; tail -n 100 \"$es_log_dir\"/*slowlog* 2>/dev/null; else printf '%s\\n' INSPECT_ELASTICSEARCH_SLOWLOG_NOT_CONFIGURED; fi"
    if metric_id == "local.elasticsearch.security.accounts":
        status = " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
        return prefix + "; " + api("/_security/user?pretty") + status + "; " + api("/_security/role?pretty") + status
    if metric_id == "local.elasticsearch.certificate.validity":
        return prefix + "; if test -z \"$es_cert\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_CERT_NOT_FOUND; else openssl x509 -in \"$es_cert\" -noout -dates -checkend 2592000; fi"
    if metric_id == "local.elasticsearch.snapshot.repository":
        repos = _elasticsearch_shell_words(_elasticsearch_candidates(profile, "elasticsearch_snapshot_repo")) or ""
        repo = repos.split()[0] if repos else ""
        status = " -w '\\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\\n'"
        verify = api(f"/{repo}/_verify?pretty", "-X POST") + status
        return prefix + f"; if test -z \"$es_endpoint\" || test -z \"{repos}\"; then printf '%s\\n' INSPECT_ELASTICSEARCH_SNAPSHOT_NOT_FOUND; else " + api("/_snapshot/_all?pretty") + status + "; " + verify + "; fi"
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
    confs = _nginx_shell_words(_nginx_path_candidates(profile, "nginx_conf", "nginx.conf"))
    errors_configured = _nginx_candidates(profile, "nginx_error_log")
    if not errors_configured:
        errors_configured = _nginx_path_candidates(profile, "nginx_log", "error.log")
    accesses_configured = _nginx_candidates(profile, "nginx_access_log")
    if not accesses_configured:
        accesses_configured = _nginx_path_candidates(profile, "nginx_log", "access.log")
    errors = _nginx_shell_words(errors_configured)
    accesses = _nginx_shell_words(accesses_configured)
    # An empty candidate list must remain valid shell syntax.  ':' is only a
    # harmless loop item and is never accepted by the -x/-f checks.
    bins_loop = bins or ":"
    confs_loop = confs or ":"
    errors_loop = errors or ":"
    accesses_loop = accesses or ":"
    parts = [
        # Use the same comm/args anchored expression as the process metric.
        f"master_line=$({_NGINX_PROCESS_COMMAND} | grep -E 'nginx: master process' | head -n 1)",
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
            "nginx_listener_host=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*listen[[:space:]]+([^:;[:space:]]+):[0-9]+.*/\\1/p' | head -n 1)",
        ]
    return "; ".join(parts)


def _build_nginx_metric_command(
    metric_id: str, profile: Dict[str, Any], *, timeout_sec: int = METRIC_TIMEOUT_SEC
) -> str:
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
    if metric_id == "local.nginx.http.reachability":
        ports = _nginx_shell_words(_nginx_candidates(profile, "nginx_port"))
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + f"; nginx_ports=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*listen[[:space:]]+[^;]*:([0-9]+)[^;]*;/\\1/p; s/^[[:space:]]*listen[[:space:]]+([0-9]+)[^;]*;/\\1/p'); if test -z \"$nginx_ports\"; then nginx_ports='{ports}'; fi; if test -z \"$nginx_listener_host\"; then nginx_listener_host=127.0.0.1; fi; if test -z \"$nginx_ports\"; then printf '%s\\n' INSPECT_NGINX_HTTP_NOT_FOUND; else for port in $nginx_ports; do curl -sS -I --connect-timeout {timeout_sec} --max-time {timeout_sec} \"http://$nginx_listener_host:$port/\" | head -n 1; done; fi"
        )
    if metric_id == "local.nginx.port.listening":
        ports = _nginx_shell_words(_nginx_candidates(profile, "nginx_port"))
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + f"; nginx_ports=$(printf '%s\\n' \"$nginx_dump\" | sed -nE 's/^[[:space:]]*listen[[:space:]]+[^;]*:([0-9]+)[^;]*;/\\1/p; s/^[[:space:]]*listen[[:space:]]+([0-9]+)[^;]*;/\\1/p'); if test -z \"$nginx_ports\"; then nginx_ports='{ports}'; fi; if test -z \"$nginx_listener_host\"; then nginx_listener_host=127.0.0.1; fi; if test -z \"$nginx_ports\"; then printf '%s\\n' INSPECT_NGINX_PORT_NOT_FOUND; else for port in $nginx_ports; do netstat -lntp | grep :$port; curl -sS -I --connect-timeout {timeout_sec} --max-time {timeout_sec} \"http://$nginx_listener_host:$port/\" | head -n 1; done; fi"
        )
    if metric_id == "local.nginx.error_log.key_evidence":
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + "; if test -z \"$nginx_error_log\"; then printf '%s\\n' INSPECT_NGINX_ERROR_LOG_NOT_FOUND; else printf '%s\\n' \"$nginx_error_log\"; tail -n 1000 \"$nginx_error_log\" | egrep -i 'emerg|alert|crit|error|permission denied|bind\\(|connect\\(\\) failed|upstream timed out' | tail -n 20; fi"
        )
    if metric_id == "local.nginx.access_log.status_codes":
        return (
            _nginx_discovery_prefix(profile, include_dump=True)
            + "; if test -z \"$nginx_access_log\"; then printf '%s\\n' INSPECT_NGINX_ACCESS_LOG_NOT_FOUND; else printf '%s\\n' \"$nginx_access_log\"; tail -n 1000 \"$nginx_access_log\" | grep -E ' [1-5][0-9][0-9] '; fi"
        )
    if metric_id == "local.nginx.fd.process.limits":
        return (
            _nginx_discovery_prefix(profile, include_dump=False)
            + "; nginx_pid=$(printf '%s\\n' \"$master_line\" | sed -nE 's/^[[:space:]]*([0-9]+).*/\\1/p'); if test -z \"$nginx_pid\" || ! test -r \"/proc/$nginx_pid/limits\"; then printf '%s\\n' INSPECT_NGINX_LIMITS_NOT_FOUND; else sed -nE '/^Max open files[[:space:]]|^Max processes[[:space:]]/p' \"/proc/$nginx_pid/limits\"; fi"
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


def _nginx_replay_command(metric_id: str, profile: Dict[str, Any]) -> Optional[str]:
    """Return a concrete, safe manual replay command for a Nginx fact.

    Runtime discovery commands deliberately stay out of reports.  Only static
    one-line commands with concrete profile values are returned here; facts
    that require a discovered PID or certificate path fail closed to the shared
    replay fallback (represented by ``None``).
    """
    if metric_id == "local.nginx.http.reachability":
        ports = _nginx_candidates(profile, "nginx_port")
        if ports:
            return f"curl -sS --connect-timeout 3 -I http://localhost:{ports[0]}/"
        return None
    # No safe static command can bind a discovered master PID for /proc limits,
    # or discover an HTTPS certificate path and then run openssl without shell
    # composition.  Keep both facts on the mandated fail-closed fallback.
    return None


def _keepalived_discovery_prefix(profile: Dict[str, Any], *, include_log: bool = False) -> str:
    """Discover Keepalived's running binary/config before using fallbacks."""
    bins = _keepalived_shell_words(_keepalived_candidates(profile, "keepalived_bin"))
    confs = _keepalived_shell_words(
        _keepalived_path_candidates(profile, "keepalived_conf", "keepalived.conf")
    )
    logs = _keepalived_shell_words(
        _keepalived_path_candidates(profile, "keepalived_log", "keepalived.log")
    )
    bins_loop = bins or ":"
    confs_loop = confs or ":"
    logs_loop = logs or ":"
    parts = [
        f"process_line=$({_KEEPALIVED_PROCESS_COMMAND} | head -n 1)",
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


def _build_keepalived_metric_command(
    metric_id: str, profile: Dict[str, Any], *, timeout_sec: int = METRIC_TIMEOUT_SEC
) -> str:
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
            + f"if test -z \"$keepalived_vips\"; then keepalived_vips='{vips}'; fi; keepalived_port='{ports}'; if test -z \"$keepalived_vips\" || test -z \"$keepalived_port\"; then printf '%s\\n' INSPECT_KEEPALIVED_VIP_NOT_FOUND; else for vip in $keepalived_vips; do vip=${{vip%%/*}}; for port in $keepalived_port; do printf 'CONFIG_ACCESS=%s:%s\\n' \"$vip\" \"$port\"; curl -sS -I --connect-timeout {timeout_sec} --max-time {timeout_sec} \"http://$vip:$port/\" | head -n 1; done; done; fi"
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
    timeout_sec: Optional[int] = None,
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
    - 未传 timeout_sec 时沿用 metrics.py 定义（普通 10s，日志类 15s）；
      CLI 会把 inspect.conf 的全局 timeout_sec 传入，覆盖所有指标；
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
    if timeout_sec is not None and not (
        MIN_COMMAND_TIMEOUT_SEC <= timeout_sec <= MAX_COMMAND_TIMEOUT_SEC
    ):
        raise CommandConfigError(
            "全局 timeout 超出范围（允许 "
            f"{MIN_COMMAND_TIMEOUT_SEC}-{MAX_COMMAND_TIMEOUT_SEC}s）: {timeout_sec}"
        )
    specs: List[CommandSpec] = []
    for m in metrics:
        metric_id = m["metric_id"]
        entry = _COMMAND_TEMPLATES.get(metric_id)
        if entry is None:
            raise CommandConfigError(
                f"allow-list 注册表缺少指标定义: {metric_id}（AE §4.1 唯一来源）"
            )
        metric_timeout_sec = m.get("timeout_sec")
        if metric_timeout_sec not in (METRIC_TIMEOUT_SEC, LOG_METRIC_TIMEOUT_SEC):
            raise CommandConfigError(
                f"指标超时越界（允许 {METRIC_TIMEOUT_SEC}/{LOG_METRIC_TIMEOUT_SEC}s）: "
                f"{metric_id}={metric_timeout_sec!r}"
            )
        effective_timeout_sec = (
            timeout_sec if timeout_sec is not None else metric_timeout_sec
        )
        required = probe_mod.metric_required_commands(metric_id)
        if not required and metric_id.startswith("local.zookeeper."):
            # probe.py is a frozen shared contract; ZooKeeper's read-only
            # command family uses the same minimal shell gate as the other
            # additional middleware adapters.
            required = ("bash",)
        if not required:
            raise CommandConfigError(f"指标所需命令映射缺失: {metric_id}")
        if metric_id in _ADDITIONAL_COMMANDS:
            command = _build_additional_command(metric_id, profile)
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=effective_timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_ADDITIONAL_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                )
            )
            continue
        # Nginx is process-discovered.  Its command must still be emitted
        # when inspect.conf has no candidate values so that the target can
        # report UNKNOWN (rather than being mislabeled UNSUPPORTED_PROFILE).
        if (
            metric_id.startswith("local.nginx.")
            and metric_id != NGINX_PROCESS_METRIC
            and _is_runtime_nginx_profile(profile)
        ):
            command = _build_nginx_metric_command(
                metric_id, profile, timeout_sec=effective_timeout_sec
            )
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=effective_timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_NGINX_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                    replay_command=_nginx_replay_command(metric_id, profile),
                )
            )
            continue
        if (
            metric_id.startswith("local.keepalived.")
            and metric_id != KEEPALIVED_PROCESS_METRIC
            and metric_id not in {
                "local.keepalived.vip.present",
                "local.keepalived.vrrp.role",
                "local.keepalived.health_check.status",
            }
            and _is_runtime_keepalived_profile(profile)
        ):
            command = _build_keepalived_metric_command(
                metric_id, profile, timeout_sec=effective_timeout_sec
            )
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=effective_timeout_sec,
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
            command = _build_elasticsearch_metric_command(
                metric_id, profile, timeout_sec=effective_timeout_sec
            )
            task_environment = _elasticsearch_task_environment(profile)
            specs.append(
                CommandSpec(
                    metric_id=metric_id,
                    command=command,
                    timeout_sec=effective_timeout_sec,
                    become=bool(entry["become"]),
                    required_commands=required,
                    source_anchor=entry["anchor"],
                    allowed_binaries=_ELASTICSEARCH_GENERATED_ALLOWED_BINARIES,
                    trusted_generated_shell=True,
                    # Keep every managed-host task on raw.  The target only
                    # needs an SSH shell; it does not need the controller's
                    # Ansible package or any system Python installation.
                    module="ansible.builtin.raw",
                    task_environment=task_environment,
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
                    timeout_sec=effective_timeout_sec,
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
                    timeout_sec=effective_timeout_sec,
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
                    timeout_sec=effective_timeout_sec,
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


def validate_command_specs(
    specs: Sequence[CommandSpec], *, require_script_path: bool = True
) -> None:
    """allow-list 校验（AE §4.1 / RK-R3-03）：拒绝未登记命令/越权参数。

    拒绝条件（任一即 CommandNotAllowedError，退出码 10）：
      - 未登记指标（注册表外 metric_id）；
      - 命令可执行名超出该指标注册表模板的可执行名集合（含注入尝试）；
      - 命令含命令替换/变量展开指示符（`$`/反引号，含引号内）——
        parse_binaries 抛错，注入一律拒绝（T-103F H-1/H-2）；
      - 超时不在安全范围（1-60s；CLI 的 inspect.conf 通常统一为 3s）；
      - become 与注册表声明不一致（最小化 become 边界，AE §5）；
      - command=None 但 error_code 非 UNSUPPORTED_PROFILE。
    """
    for spec in specs:
        entry = _COMMAND_TEMPLATES.get(spec.metric_id)
        if entry is None:
            raise CommandNotAllowedError(
                f"allow-list 拒绝：指标未登记: {spec.metric_id!r}"
            )
        if not MIN_COMMAND_TIMEOUT_SEC <= spec.timeout_sec <= MAX_COMMAND_TIMEOUT_SEC:
            raise CommandNotAllowedError(
                "allow-list 拒绝：超时越界（允许 "
                f"{MIN_COMMAND_TIMEOUT_SEC}-{MAX_COMMAND_TIMEOUT_SEC}s）: "
                f"{spec.metric_id}={spec.timeout_sec}"
            )
        if bool(spec.become) != bool(entry["become"]):
            raise CommandNotAllowedError(
                f"allow-list 拒绝：become 与注册表声明不一致（最小化 become）: "
                f"{spec.metric_id}={spec.become!r}"
            )
        if spec.module != "ansible.builtin.raw":
            raise CommandNotAllowedError(
                "allow-list 拒绝：受控端任务必须使用 ansible.builtin.raw，"
                f"避免依赖受控端 Python: {spec.metric_id}={spec.module!r}"
            )
        # task_environment is rendered as a Jinja lookup prefix by the raw
        # task generator.  It never becomes a literal credential in the
        # generated playbook.
        allowed_environment = {
            "INSPECT_ES_API_USER",
            "INSPECT_ES_API_PASSWORD",
        }
        if any(key not in allowed_environment for key in spec.task_environment):
            raise CommandNotAllowedError(
                f"allow-list 拒绝：任务环境变量不在私有认证集合内: {spec.metric_id}"
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
                or spec.metric_id in _ADDITIONAL_COMMANDS
            ):
                raise CommandNotAllowedError(
                    f"allow-list 拒绝：只有已注册中间件动态命令可使用内部 shell 变量: {spec.metric_id}"
                )
            if spec.metric_id.startswith("local.nginx."):
                unsafe_tokens = _NGINX_UNSAFE_GENERATED_TOKENS
            elif spec.metric_id.startswith("local.keepalived."):
                unsafe_tokens = _KEEPALIVED_UNSAFE_GENERATED_TOKENS
            elif spec.metric_id.startswith("local.elasticsearch."):
                unsafe_tokens = _ELASTICSEARCH_UNSAFE_GENERATED_TOKENS
            else:
                unsafe_tokens = _ADDITIONAL_UNSAFE_GENERATED_TOKENS
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


def _metric_bundle_module(metric_id: str) -> str:
    """Return the stable remote collection bundle for a metric.

    Bundling is deliberately module-oriented rather than one giant host
    command.  This keeps middleware adapters isolated while reducing the
    Ansible/raw task count on the managed host.
    """

    for prefix, module_id in (
        ("local.nginx.", "nginx"),
        ("local.keepalived.", "keepalived"),
        ("local.elasticsearch.", "elasticsearch"),
    ):
        if metric_id.startswith(prefix):
            return module_id
    return "linux"


def _metric_bundle_groups(
    specs: Sequence[CommandSpec],
) -> List[Tuple[Tuple[Any, ...], List[CommandSpec]]]:
    """Group executable specs by module, privilege and secret environment.

    A privileged metric is kept in a separate bundle so a single ``become``
    declaration cannot accidentally elevate all commands in a module.  The
    environment values are part of the grouping key to prevent credentials
    for different generated tasks from being mixed.
    """

    groups: Dict[Tuple[Any, ...], List[CommandSpec]] = {}
    for spec in specs:
        if spec.command is None:
            continue
        env_items = tuple(sorted(spec.task_environment.items()))
        key = (
            _metric_bundle_module(spec.metric_id),
            bool(spec.become),
            env_items,
        )
        groups.setdefault(key, []).append(spec)
    return list(groups.items())


def _metric_bundle_task_name(index: int, key: Tuple[Any, ...]) -> str:
    module_id, privileged, _env_items = key
    privilege = "privileged" if privileged else "unprivileged"
    return f"metric-bundle: {module_id} #{index} ({privilege})"


def _render_metric_bundle(specs: Sequence[CommandSpec]) -> str:
    """Render one raw-compatible shell command with per-metric markers.

    Every inner command keeps its own timeout and is followed by an explicit
    return-code marker.  The outer command intentionally has no aggregate
    timeout: the inner timeouts bound each read-only probe while allowing the
    rest of the module bundle to continue after one slow metric.
    """

    lines = ["set +e"]
    for spec in specs:
        # metric_id is registry-owned and therefore safe as a single-quoted
        # marker value; command remains shell-escaped at the existing raw
        # command boundary below.
        metric_id = _sh_escape(spec.metric_id)
        command = _sh_escape(spec.command or "")
        lines.extend(
            [
                f"printf '%s\\t%s\\n' INSPECT_METRIC_BEGIN '{metric_id}'",
                f"timeout {spec.timeout_sec} /bin/bash -lc '{command}' 2>&1",
                "inspect_metric_rc=$?",
                "printf '\\n'",
                f"printf '%s\\t%s\\t%s\\n' INSPECT_METRIC_END '{metric_id}' \"$inspect_metric_rc\"",
            ]
        )
    # Keep the YAML scalar single-line.  YAML folds multiline single-quoted
    # scalars, which would otherwise remove shell command boundaries.
    return "; ".join(lines)


def _parse_metric_bundle_output(text: str) -> Dict[str, Dict[str, Any]]:
    """Split marked bundle stdout into the existing per-metric raw shape."""

    results: Dict[str, Dict[str, Any]] = {}
    pattern = re.compile(
        r"INSPECT_METRIC_BEGIN\t(?P<metric>[^\t\r\n]+)\r?\n"
        r"(?P<stdout>.*?)"
        r"\r?\nINSPECT_METRIC_END\t(?P=metric)\t(?P<rc>-?\d+)(?:\r?\n|$)",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        metric_id = match.group("metric")
        if metric_id in results:
            continue
        results[metric_id] = {
            "rc": int(match.group("rc")),
            "stdout": match.group("stdout"),
            "stderr": "",
        }
    return results


def generate_playbook(
    specs: Sequence[CommandSpec],
    probe_command: Optional[str] = None,
    timeout_sec: Optional[int] = None,
    parallel: int = 1,
) -> str:
    """生成采集 playbook 文本（YAML）。

    契约（AE §1-§7 文本断言）：
      - play 级：hosts: all、gather_facts: false、serial: 1、ignore_unreachable: true；
      - 探测任务与按模块/权限分组的 metric-bundle 任务均使用
        ansible.builtin.raw；bundle 内每个指标保留自己的
        `timeout N /bin/bash -lc '…'`（AE §7 超时注入）；
      - become：仅包含注册表声明需要特权的 bundle 使用 become: true（AE §5
        最小化 become），其余 false；
      - 无 retries/until（AE §7：超时/连接失败不自动重试）；
      - 忽略单命令失败（rc 语义留给 normalize，T-104）：ignore_errors。
    """
    collection_timeout_sec = (
        timeout_sec if timeout_sec is not None else PROBE_TIMEOUT_SEC
    )
    if not MIN_COMMAND_TIMEOUT_SEC <= collection_timeout_sec <= MAX_COMMAND_TIMEOUT_SEC:
        raise CommandConfigError(
            "全局 timeout 超出范围（允许 "
            f"{MIN_COMMAND_TIMEOUT_SEC}-{MAX_COMMAND_TIMEOUT_SEC}s）: "
            f"{collection_timeout_sec}"
        )
    if parallel != 1:
        raise CommandConfigError(
            f"单主机 playbook 必须使用 serial: 1，不能设置为 {parallel}；"
            "主机并发由控制端线程池负责"
        )
    probe_command = probe_command or probe_mod.build_probe_command(
        timeout_sec=collection_timeout_sec
    )
    lines = [
        "---",
        "# inspect 采集 playbook（T-103 ansible_runner 生成；ansible-execution v1）",
        "# 契约：gather_facts:false / serial:1 / raw|script + /bin/bash -lc / 最小化 become /",
        "#       只读命令 allow-list / 每命令超时注入（由 inspect.conf timeout 统一控制、",
        "#       单主机 300s）/ 无重试（AE §1-§7；超时与连接失败不自动重试）",
        '- name: "inspect collection"',
        "  hosts: all",
        "  gather_facts: false",
        "  serial: 1",
        "  ignore_unreachable: true",
        "  tasks:",
    ]
    lines.append(f'    - name: "probe: 能力探测（{collection_timeout_sec}s）"')
    lines.append(
        f"      ansible.builtin.raw: '{_yaml_single_quote(probe_command)}'"
    )
    lines.append("      become: false")
    lines.append("      register: inspect_probe")
    lines.append("      ignore_errors: true")
    for idx, (key, bundle_specs) in enumerate(_metric_bundle_groups(specs)):
        _module_id, _privileged, env_items = key
        env_prefix = ""
        if env_items:
            env_prefix = " ".join(
                f'export {env_key}={{{{ lookup("env", "{env_key}") | quote }}}};'
                for env_key, _env_value in env_items
            ) + " "
        raw_cmd = f"{env_prefix}{_render_metric_bundle(bundle_specs)}"
        lines.append(
            f'    - name: "{_metric_bundle_task_name(idx, key)}"'
        )
        lines.append(
            f"      {bundle_specs[0].module}: '{_yaml_single_quote(raw_cmd)}'"
        )
        lines.append(f"      become: {str(bool(key[1])).lower()}")
        # A connection failure during the probe must not cause Ansible to
        # reopen the same SSH connection for every metric task.  The probe is
        # the host-level gate; an unreachable result skips the remaining
        # bundle tasks locally and lets the callback report one host-level
        # ERROR.
        lines.append("      when: inspect_probe is not unreachable")
        lines.append(f"      register: inspect_bundle_{idx}")
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
    timeout_sec: int = PROBE_TIMEOUT_SEC
    parallel: int = DEFAULT_PARALLEL_HOSTS


def _default_runtime_dir() -> Path:
    return Path(__file__).resolve().parent.parent / _RUNTIME_DIR_NAME


def prepare_run(
    selection: Any,
    specs: Sequence[CommandSpec],
    runtime_dir: Optional[Path] = None,
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
    timeout_sec: Optional[int] = None,
    parallel: int = DEFAULT_PARALLEL_HOSTS,
    cleanup_inventory: bool = True,
) -> RunPlan:
    """allow-list 校验 → 生成 playbook 与 argv → RunPlan（不执行不连接）。

    selection：inventory.HostSelection 鸭子类型（.inventory_file/.hosts/
    .limit）；playbook 写入 runtime_dir（默认 <仓库根>/.runtime）。
    nginx_whitelist：Nginx 白名单 IP（白名单内未运行 → CRIT「未运行」；
    白名单外未运行 → 跳过该主机 Nginx 指标）。
    """
    # Validate all command and generated-shell constraints before writing any
    # runtime file.  All managed-host tasks remain raw, so no controller-side
    # script upload or target-side Python interpreter is required.
    validate_command_specs(specs, require_script_path=False)
    if not MIN_PARALLEL_HOSTS <= parallel <= MAX_PARALLEL_HOSTS:
        raise CommandConfigError(
            f"远程并发主机数超出范围（允许 {MIN_PARALLEL_HOSTS}-{MAX_PARALLEL_HOSTS}）: {parallel}"
        )
    runtime_dir = Path(runtime_dir) if runtime_dir is not None else _default_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    playbook_path = runtime_dir / f"playbook-{uuid.uuid4().hex[:8]}.yml"
    prepared_specs: List[CommandSpec] = list(specs)
    collection_timeout_sec = (
        timeout_sec if timeout_sec is not None else PROBE_TIMEOUT_SEC
    )
    try:
        validate_command_specs(prepared_specs)
        text = generate_playbook(
            prepared_specs, timeout_sec=collection_timeout_sec, parallel=1
        )
        playbook_path.write_text(text, encoding="utf-8", newline="\n")
        playbook_path.chmod(0o600)
    except OSError as exc:
        for path in [playbook_path]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        raise CommandConfigError(
            f"运行期 playbook/script 写入失败（{type(exc).__name__}）"
        ) from exc
    except CommandConfigError:
        for path in [playbook_path]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        raise
    plan = RunPlan(
        playbook_path=playbook_path,
        inventory_file=Path(selection.inventory_file),
        hosts=list(selection.hosts),
        limit=selection.limit,
        metric_specs=prepared_specs,
        probe_command=probe_mod.build_probe_command(
            timeout_sec=collection_timeout_sec
        ),
        cleanup_paths=(
            (playbook_path, Path(selection.inventory_file))
            if cleanup_inventory and getattr(selection, "kind", None) in {"local", "hosts"}
            else (playbook_path,)
        ),
        selection_kind=str(getattr(selection, "kind", "unknown")),
        nginx_whitelist=tuple(nginx_whitelist or ()),
        keepalived_whitelist=tuple(keepalived_whitelist or ()),
        elasticsearch_whitelist=tuple(elasticsearch_whitelist or ()),
        timeout_sec=collection_timeout_sec,
        parallel=parallel,
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
    if rc in {TIMEOUT_RC, CURL_TIMEOUT_RC}:
        return {
            "metric_id": metric_id,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "error": _error(
                ERROR_TIMEOUT,
                "命令超时（timeout/curl 达到 inspect.conf timeout，AE §7）",
            ),
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
MIDDLEWARE_METRIC_PREFIXES = (
    "local.kafka.", "local.mysql.", "local.nacos.", "local.rabbitmq.",
    "local.redis.", "local.rocketmq.", "local.tomcat.", "local.zookeeper.",
    "local.keepalived.",
)


def select_middleware_metrics(
    metric_results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Drop every metric in a module when its process gate reports stopped."""
    results = list(metric_results)
    stopped_modules = set()
    for item in results:
        metric_id = str(item.get("metric_id", ""))
        if not metric_id.startswith(MIDDLEWARE_METRIC_PREFIXES):
            continue
        stdout = str(item.get("stdout") or "")
        match = re.search(r"INSPECT_MIDDLEWARE_NOT_RUNNING=([a-z0-9_]+)", stdout)
        if match:
            stopped_modules.add(match.group(1))
    if not stopped_modules:
        return results
    return [
        item for item in results
        if not any(
            str(item.get("metric_id", "")).startswith(f"local.{module_id}.")
            for module_id in stopped_modules
        )
    ]


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
        if spec.replay_command is not None:
            result["replay_command"] = spec.replay_command
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
        metric_results = select_middleware_metrics(metric_results)
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


def _callback_error_for_probe_not_executed() -> Dict[str, str]:
    """分类 callback 未出现 probe 任务的主机，避免误报为 bash 缺失。"""
    return _error(
        ERROR_CONNECTION_FAILED,
        "Ansible 未收到该主机的能力探测回调（主机未执行或连接失败，无业务结论）",
    )


def _cleanup_plan_files(plan: RunPlan) -> List[str]:
    """Remove generated files without Python 3.8-only APIs."""
    return _cleanup_paths(plan.cleanup_paths)


def _cleanup_paths(paths: Sequence[Path]) -> List[str]:
    """Remove generated files and return only sanitized failure names."""
    failures: List[str] = []
    for path in paths:
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
        env["ANSIBLE_SSH_COMMON_ARGS"] += (
            f" -o ConnectTimeout={plan.timeout_sec}"
        )
        env["ANSIBLE_TIMEOUT"] = str(plan.timeout_sec)
        # The generated script task resolves these values through Ansible's
        # controller-side env lookup.  This keeps the private API credentials
        # out of the playbook, argv, callback, and fact source while still
        # allowing raw-compatible execution on target hosts with Python 3.7.
        for spec in plan.metric_specs:
            for key, value in getattr(spec, "task_environment", {}).items():
                if key in {"INSPECT_ES_API_USER", "INSPECT_ES_API_PASSWORD"}:
                    env[key] = value
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
    bundle_specs_by_task = {
        _metric_bundle_task_name(index, key): bundle_specs
        for index, (key, bundle_specs) in enumerate(
            _metric_bundle_groups(plan.metric_specs)
        )
    }

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
                if task_name.startswith("metric-bundle:"):
                    bundle_specs = bundle_specs_by_task.get(task_name, ())
                    if not bundle_specs:
                        continue
                    # Do not apply the per-task diagnostic cap before
                    # splitting.  A legitimate log/JSON body in an early
                    # metric must not hide markers for later metrics in the
                    # same bundle.  Each extracted metric is capped below.
                    bundle_stdout = raw.get("stdout")
                    if not isinstance(bundle_stdout, str):
                        bundle_stdout = ""
                    bundled = _parse_metric_bundle_output(bundle_stdout)
                    for spec in bundle_specs:
                        part = bundled.get(spec.metric_id)
                        if part is None:
                            metric_result = classify_metric_result(
                                spec.metric_id,
                                None,
                                "",
                                "",
                                spec.required_commands,
                                state["probe_matrix"],
                                preset_error={
                                    "code": ERROR_DATA_MISSING,
                                    "message": "Ansible metric-bundle 缺少该指标标记",
                                },
                            )
                        else:
                            metric_result = classify_metric_result(
                                spec.metric_id,
                                part["rc"],
                                _callback_text(part["stdout"]),
                                _callback_text(part["stderr"]),
                                spec.required_commands,
                                state["probe_matrix"],
                            )
                        metric_result["command"] = spec.command or ""
                        if spec.replay_command is not None:
                            metric_result["replay_command"] = spec.replay_command
                        state["metrics"][spec.metric_id] = metric_result
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
                if spec.replay_command is not None:
                    metric_result["replay_command"] = spec.replay_command
                state["metrics"][metric_id] = metric_result

    stats = payload.get("stats") or {}
    if isinstance(stats, dict):
        for host_name, stat in stats.items():
            state = states.get(str(host_name))
            if state is not None and isinstance(stat, dict) and stat.get("unreachable", 0):
                state["host_error"] = _callback_error_for_unreachable()

    # With serial execution, an unreachable first batch can leave later hosts
    # without any task callback. Those hosts must not be reported as if their
    # bash probe actually ran and failed; classify the missing callback as a
    # host-level connection/execution failure and continue rendering others.
    for state in states.values():
        if state["host_error"] is None and not state["probe_seen"]:
            state["host_error"] = _callback_error_for_probe_not_executed()

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
                if spec.replay_command is not None:
                    metric_result["replay_command"] = spec.replay_command
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
            if spec.replay_command is not None:
                metric_result["replay_command"] = spec.replay_command
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
        metrics = select_middleware_metrics(metrics)
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


def _single_host_selection(selection: Any, host: Any) -> Any:
    """Clone a resolved selection for exactly one worker/Ansible play."""
    selected = copy(selection)
    selected.hosts = [host]
    # The inventory remains unchanged; --limit makes Ansible target only this
    # host.  This also prevents an unreachable first host from suppressing
    # callbacks for later hosts.
    selected.limit = str(host.name)
    return selected


def _run_one_host(
    selection: Any,
    host: Any,
    specs: Sequence[CommandSpec],
    *,
    fixture_dir: Optional[Path],
    runtime_dir: Optional[Path],
    nginx_whitelist: Optional[Sequence[str]],
    keepalived_whitelist: Optional[Sequence[str]],
    elasticsearch_whitelist: Optional[Sequence[str]],
    timeout_sec: Optional[int],
) -> Dict[str, Any]:
    """Worker entry point: one thread owns one host and one Ansible run."""
    plan = prepare_run(
        _single_host_selection(selection, host),
        specs,
        runtime_dir=runtime_dir,
        nginx_whitelist=nginx_whitelist,
        keepalived_whitelist=keepalived_whitelist,
        elasticsearch_whitelist=elasticsearch_whitelist,
        timeout_sec=timeout_sec,
        # A worker playbook must never fan out to another host.
        parallel=1,
        # A -H IP list can point every worker at the same temporary inventory.
        # The parent run owns that shared file and removes it after all workers
        # finish; deleting it inside a worker would race with other Ansible
        # processes.
        cleanup_inventory=False,
    )
    return execute_plan(plan, fixture_dir=fixture_dir)


def run(
    selection: Any,
    specs: Sequence[CommandSpec],
    fixture_dir: Optional[Path] = None,
    runtime_dir: Optional[Path] = None,
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
    timeout_sec: Optional[int] = None,
    parallel: int = DEFAULT_PARALLEL_HOSTS,
) -> Dict[str, Any]:
    """Collect hosts concurrently with bounded controller threads.

    The old design submitted one multi-host playbook and relied on Ansible's
    serial/parallel batches.  That made an unreachable host affect callback
    visibility for subsequent hosts and repeated the remote wait in a long
    batch.  The new contract is deliberately explicit: one host, one thread,
    one playbook, with at most ``parallel`` threads (maximum 10).
    """
    if not MIN_PARALLEL_HOSTS <= parallel <= MAX_PARALLEL_HOSTS:
        raise CommandConfigError(
            f"远程线程数超出范围（允许 {MIN_PARALLEL_HOSTS}-{MAX_PARALLEL_HOSTS}）: {parallel}"
        )
    hosts = list(getattr(selection, "hosts", ()))
    if getattr(selection, "kind", None) == "local" or len(hosts) <= 1:
        plan = prepare_run(
            selection,
            specs,
            runtime_dir=runtime_dir,
            nginx_whitelist=nginx_whitelist,
            keepalived_whitelist=keepalived_whitelist,
            elasticsearch_whitelist=elasticsearch_whitelist,
            timeout_sec=timeout_sec,
            parallel=1,
        )
        return execute_plan(plan, fixture_dir=fixture_dir)

    started = time.monotonic()
    worker_count = min(parallel, len(hosts), MAX_PARALLEL_HOSTS)
    by_name: Dict[str, Dict[str, Any]] = {}
    failures: List[BaseException] = []
    shared_cleanup_failures: List[str] = []
    try:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="inspect-host",
        ) as pool:
            future_to_host = {
                pool.submit(
                    _run_one_host,
                    selection,
                    host,
                    specs,
                    fixture_dir=fixture_dir,
                    runtime_dir=runtime_dir,
                    nginx_whitelist=nginx_whitelist,
                    keepalived_whitelist=keepalived_whitelist,
                    elasticsearch_whitelist=elasticsearch_whitelist,
                    timeout_sec=timeout_sec,
                ): host
                for host in hosts
            }
            for future in as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    result = future.result()
                except BaseException as exc:  # propagate the first typed runner error
                    failures.append(exc)
                    continue
                for host_result in result.get("hosts", []):
                    by_name[str(host_result.get("host"))] = host_result
    finally:
        # ``-H`` without a configured inventory creates one shared temporary
        # inventory.  It must outlive every worker's Ansible process.
        if getattr(selection, "kind", None) == "hosts":
            shared_cleanup_failures = _cleanup_paths((Path(selection.inventory_file),))

    if failures:
        raise failures[0]

    ordered = [by_name[str(host.name)] for host in hosts if str(host.name) in by_name]
    result = {
        "execution_status": run_status_for_hosts(ordered),
        "hosts": ordered,
        "real_mode": True if not _resolve_fixture_dir(fixture_dir) else False,
        "fixture_mode": bool(_resolve_fixture_dir(fixture_dir)),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    if shared_cleanup_failures:
        result["cleanup_diagnostic"] = {
            "category": "runtime_cleanup_failed",
            "return_code": None,
            "check": "remove generated runtime files manually",
            "files": shared_cleanup_failures,
        }
    return result


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
    "DEFAULT_PARALLEL_HOSTS",
    "MIN_PARALLEL_HOSTS",
    "MAX_PARALLEL_HOSTS",
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
    "select_middleware_metrics",
    "validate_command_specs",
]
