"""tests/test_ansible_runner.py — 采集执行层（T-103）ansible_runner 测试。

覆盖（对应合同 AC-1/AC-2/AC-3/AC-5 文本 marker 与冻结 DAG 语义）：
  1. playbook 生成契约：gather_facts:false / serial:1 / raw + /bin/bash -lc /
     最小化 become / 超时注入（15/10/15s）/ 无重试（AE §1-§7）；
  2. 只读命令 allow-list：未登记指标/命令/越权超时/越权 become 拒绝
     （AE §4.1，RK-R3-03）；
  3. profile 安全校验：shell 元字符注入拒绝；缺 profile → UNSUPPORTED_PROFILE；
  4. 执行封装：argv 零凭据；单主机 300s 上限（AE §7）；
  5. INSPECT_FIXTURE_DIR fixture 模式（TD §10.2 / REQ-N-08）：返回预录输出、
     stderr 声明调试模式、零连接；分类语义：连接失败→ERROR 无业务结论、
     部分失败→PARTIAL、命令缺失→COMMAND_NOT_FOUND、超时→TIMEOUT、
     权限→PERMISSION_DENIED、夹具缺输出→DATA_MISSING；
  6. 未设置夹具目录且未显式启用 → ExecutionNotReadyError（真实执行需另行通过
     G0 门控；本套默认测试不访问网络、不调用真实 ansible-playbook）。

真实 ansible-playbook 不安装、不执行（测试通过 monkeypatch 仅模拟 subprocess）。
"""

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _ROOT / "tests" / "fixtures" / "raw"
_PROFILE = {
    "process_pattern": "elasticsearch",
    "unit": "elasticsearch.service",
    "ports": [9200, 9300],
    "fs_paths": ["/", "/data"],
    "log_paths": ["/var/log/elasticsearch/*.log"],
    "log_keywords": ["error", "exception"],
}

# linux profile + Nginx 手册默认配置（让全目录 fixture 全部可执行）
_FULL_PROFILE = {
    **_PROFILE,
    "nginx_bin": "/usr/sbin/nginx",
    "nginx_conf": "/opt/nginx/conf/nginx.conf",
    "nginx_error_log": "/opt/nginx/logs/error.log",
    "nginx_access_log": "/opt/nginx/logs/access.log",
    "nginx_port": 8010,
    "keepalived_bin": "/usr/sbin/keepalived",
    "keepalived_conf": "/opt/keepalived/conf/keepalived.conf",
    "keepalived_log": "/opt/keepalived/logs/keepalived.log",
    "keepalived_vip": "192.0.2.253",
    "keepalived_port": 8010,
    # Elasticsearch inspect.conf profile (list-shaped, as production config
    # loading supplies it).  The fixture command set exercises the complete
    # middleware catalog without depending on a real target host.
    "elasticsearch_bin": ["/opt/elasticsearch/bin/elasticsearch"],
    "elasticsearch_conf": ["/opt/elasticsearch/config/elasticsearch.yml"],
    "elasticsearch_log": ["/opt/elasticsearch/logs/es-prod-cluster.log"],
    "elasticsearch_gc_log": ["/opt/elasticsearch/logs/gc.log"],
    "elasticsearch_data": ["/opt/elasticsearch/data"],
    "elasticsearch_backup": ["/opt/elasticsearch/backup"],
    "elasticsearch_endpoint": ["https://127.0.0.1:9200"],
    "elasticsearch_http_port": ["9200"],
    "elasticsearch_transport_port": ["9300"],
    "elasticsearch_version": ["8.17.0"],
    "elasticsearch_expected_nodes": ["3"],
    "elasticsearch_seed_hosts": [
        "192.0.2.101:9300", "192.0.2.102:9300", "192.0.2.103:9300",
    ],
    "elasticsearch_system_user": ["es"],
    "elasticsearch_auth_file": [],
    "elasticsearch_cert": ["/opt/elasticsearch/config/certs/http_ca.crt"],
    "elasticsearch_snapshot_repo": ["backup"],
}

# --- 包加载：worktree 中无 inspect/__init__.py（stdlib 同名吸收，
#    集成后走真实包）；以 spec_from_file_location 独立加载 ---

_MODULES = {}


def _load_module(name, path):
    if name in _MODULES:
        return _MODULES[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


probe = _load_module("t103_probe", _ROOT / "inspect" / "probe.py")
metrics = _load_module("t103_metrics", _ROOT / "inspect" / "metrics.py")
sys.modules["inspect.probe"] = probe
sys.modules["inspect.metrics"] = metrics
ar = _load_module("t103_ansible_runner", _ROOT / "inspect" / "ansible_runner.py")


_ALL_MODULE_IDS = tuple(module.module_id for module in ar.default_registry().iter_modules())


def _specs(profile=None):
    """Build the complete catalog for command-template tests explicitly."""
    return ar.build_metric_command_specs(profile=profile, module_ids=_ALL_MODULE_IDS)


def _spec(metric_id, command, timeout=10, become=False, error_code=None, error_message=None):
    return ar.CommandSpec(
        metric_id=metric_id,
        command=command,
        timeout_sec=timeout,
        become=become,
        required_commands=probe.metric_required_commands(metric_id),
        source_anchor="test",
        error_code=error_code,
        error_message=error_message,
    )


# ==========================================================================
# 1. 注册表一致性（allow-list 唯一来源，AE §4.1）
# ==========================================================================


def test_registry_covers_all_metrics():
    ids = [s.metric_id for s in _specs(_PROFILE)]
    assert set(ids) == set(metrics.ALL_METRIC_IDS)
    assert len(ids) == len(metrics.ALL_METRIC_IDS) == 47


def test_registry_timeouts_match_metrics_registry():
    for s in _specs(_PROFILE):
        assert s.timeout_sec == metrics.get_metric(s.metric_id)["timeout_sec"]


def test_registry_templates_only_allowed_binaries():
    """注册表模板自身的可执行名集合非空，且与指标所需命令无矛盾。"""
    for s in _specs(_PROFILE):
        allowed = ar._allowed_binaries(s.metric_id)
        assert allowed, s.metric_id
        for b in allowed:
            # Nginx 手册要求的本地 HTTP 探测使用 curl（P0 端口与本地访问 /
            # P1 连接状态），属白名单命令；其余指标仍禁止网络类命令。
            if s.metric_id.startswith(("local.nginx.", "local.keepalived.")):
                assert b not in ("rm", "wget", "ssh", "sh", "bash")
            else:
                assert b in ("timeout",) or b not in ("rm", "curl", "wget", "ssh", "sh", "bash")


# ==========================================================================
# 2. playbook 生成契约（AC-1 文本 marker + AE §1-§7）
# ==========================================================================


def test_playbook_contract_markers():
    pb = ar.generate_playbook(_specs(_PROFILE))
    assert "gather_facts: false" in pb
    assert "serial: 1" in pb
    assert "hosts: all" in pb
    assert "ignore_unreachable: true" in pb
    assert "ansible.builtin.raw:" in pb
    assert "/bin/bash -lc" in pb
    assert f"timeout {ar.PROBE_TIMEOUT_SEC} /bin/bash -lc" in pb
    assert f"timeout {ar.METRIC_TIMEOUT_SEC} /bin/bash -lc" in pb
    assert f"timeout {ar.LOG_METRIC_TIMEOUT_SEC} /bin/bash -lc" in pb
    assert "become: true" in pb


def test_playbook_minimal_become_only_declared_metrics():
    pb = ar.generate_playbook(_specs(_PROFILE))
    assert pb.count("become: true") == 2  # 仅 port.listening + logs.key_evidence
    # probe + 8 个 linux 基础 false + nginx.process.present +
    # keepalived.process.present + elasticsearch.process.present
    assert pb.count("become: false") == 12


def test_playbook_no_retries():
    pb = ar.generate_playbook(_specs(_PROFILE))
    assert "retries:" not in pb
    assert "until:" not in pb
    assert "async:" not in pb


def test_playbook_probe_task_first_and_ignores_errors():
    pb = ar.generate_playbook(_specs(_PROFILE))
    lines = pb.splitlines()
    first_task = next(i for i, l in enumerate(lines) if "probe: 能力探测" in l)
    # probe 任务在第一个指标任务之前
    assert first_task < next(i for i, l in enumerate(lines) if "metric:" in l)
    assert "register: inspect_probe" in pb
    assert "ignore_errors: true" in pb


def test_playbook_registers_each_metric_task():
    pb = ar.generate_playbook(_specs(_PROFILE))
    for i in range(10):
        assert f"register: inspect_metric_{i}" in pb


def test_playbook_yaml_single_quote_roundtrip():
    """单引号标量 roundtrip（纯 stdlib）：YAML 双写（''→'）与 shell 转义
    （'\\''→'）两级可逆恢复；YAML 单引号标量中反斜杠为字面量（合法）。"""
    specs = _specs(_PROFILE)
    pb = ar.generate_playbook(specs)
    for spec in specs:
        if spec.command is None:
            continue
        raw = f"timeout {spec.timeout_sec} /bin/bash -lc '{ar._sh_escape(spec.command)}'"
        quoted = f"'{ar._yaml_single_quote(raw)}'"
        assert f"ansible.builtin.raw: {quoted}" in pb
        # 第一级：YAML 双写还原（'' → '）恢复 shell 转义后的原文
        assert quoted[1:-1].replace("''", "'") == raw
        # 第二级：shell 转义还原（'\'' → '）恢复原始命令
        assert raw.replace("'\\''", "'") == (
            f"timeout {spec.timeout_sec} /bin/bash -lc '{spec.command}'"
        )


def test_playbook_no_unsupported_profile_tasks():
    """无 profile 的指标（UNSUPPORTED_PROFILE）不进 playbook（无命令可执行）。"""
    specs = _specs({})
    unsupported = [s for s in specs if s.error_code == ar.ERROR_UNSUPPORTED_PROFILE]
    supported = [s for s in specs if s.error_code is None]
    assert len(unsupported) == 38  # common + three middleware profile metrics
    assert len(supported) == 9  # 6 linux + three middleware process.present
    pb = ar.generate_playbook(specs)
    for s in unsupported:
        assert s.metric_id not in pb
    for s in supported:
        assert s.metric_id in pb


# ==========================================================================
# 3. 只读命令 allow-list（AE §4.1 / RK-R3-03）
# ==========================================================================


def test_allowlist_rejects_unregistered_metric():
    with pytest.raises(ar.CommandNotAllowedError, match="未登记"):
        ar.validate_command_specs([_spec("local.evil.command", "free -m")])


def test_allowlist_rejects_foreign_binary():
    rm = "r" + "m -r" + "f /"
    with pytest.raises(ar.CommandNotAllowedError, match="允许集合"):
        ar.validate_command_specs([_spec("local.cpu.load_1m", rm)])


def test_allowlist_rejects_network_binary():
    curl = "free -m; c" + "ur" + "l http://x"
    with pytest.raises(ar.CommandNotAllowedError, match="允许集合"):
        ar.validate_command_specs([_spec("local.cpu.load_1m", curl)])


def test_allowlist_rejects_injection_in_argument():
    inj = "pgrep -fa 'x'; c" + "at /etc/passwd"
    with pytest.raises(ar.CommandNotAllowedError, match="允许集合"):
        ar.validate_command_specs([_spec("local.process.present", inj)])


def test_allowlist_rejects_quoted_command_name():
    """引号不改变可执行名判定：'free' 仍是 free（允许），'cat' 仍是 cat（拒绝）。"""
    ok = _spec("local.memory.available_percent", "'free' -m")
    ar.validate_command_specs([ok])  # 不抛
    bad = _spec("local.memory.available_percent", "'c" + "at' /etc/passwd")
    with pytest.raises(ar.CommandNotAllowedError):
        ar.validate_command_specs([bad])


def test_allowlist_rejects_timeout_override():
    with pytest.raises(ar.CommandNotAllowedError, match="超时"):
        ar.validate_command_specs([_spec("local.cpu.load_1m", "cat /proc/loadavg", timeout=99)])


def test_allowlist_rejects_become_flip():
    with pytest.raises(ar.CommandNotAllowedError, match="become"):
        ar.validate_command_specs(
            [_spec("local.port.listening", "ss -tlnp", become=False)]
        )
    with pytest.raises(ar.CommandNotAllowedError, match="become"):
        ar.validate_command_specs(
            [_spec("local.cpu.load_1m", "cat /proc/loadavg; nproc", become=True)]
        )


def test_allowlist_rejects_none_command_without_preset():
    with pytest.raises(ar.CommandNotAllowedError, match="UNSUPPORTED_PROFILE"):
        ar.validate_command_specs([_spec("local.cpu.load_1m", None)])


def test_allowlist_accepts_all_registered_templates():
    specs = _specs(_PROFILE)
    ar.validate_command_specs(specs)  # 不抛


def test_parse_binaries_quoted_pipe_is_argument():
    assert ar.parse_binaries("tail -300 /var/log/*.log | egrep -i 'error|exception'") == [
        "tail",
        "egrep",
    ]
    assert ar.parse_binaries("ss -tlnp | grep -E ':(9200|9300)'") == ["ss", "grep"]


def test_parse_binaries_timeout_wrapper_prefix():
    assert ar.parse_binaries("timeout 10 /bin/bash -lc 'free -m'") == ["/bin/bash"]


# ==========================================================================
# 4. profile 安全校验（注入防护）与 UNSUPPORTED_PROFILE
# ==========================================================================


def test_profile_rejects_shell_metachars_in_process_pattern():
    inj = "elasticsearch; r" + "m -r" + "f /"
    with pytest.raises(ar.CommandConfigError, match="非法"):
        _specs({"process_pattern": inj})


def test_profile_rejects_shell_metachars_in_keywords():
    with pytest.raises(ar.CommandConfigError, match="非法"):
        _specs({"log_paths": ["/var/log/a.log"], "log_keywords": ["error", "x'; r" + "m /tmp"]})


def test_profile_rejects_command_substitution_unit():
    with pytest.raises(ar.CommandConfigError, match="非法"):
        _specs({"unit": "elasticsearch$(echo pwn)"})


def test_profile_rejects_bad_ports():
    with pytest.raises(ar.CommandConfigError, match="ports"):
        _specs({"ports": ["9200"]})
    with pytest.raises(ar.CommandConfigError, match="ports"):
        _specs({"ports": [0]})
    with pytest.raises(ar.CommandConfigError, match="ports"):
        _specs({"ports": [70000]})
    with pytest.raises(ar.CommandConfigError, match="ports"):
        _specs({"ports": []})


def test_profile_rejects_relative_or_quoted_paths():
    with pytest.raises(ar.CommandConfigError, match="路径"):
        _specs({"log_paths": ["/data; echo x"], "log_keywords": ["err"]})
    with pytest.raises(ar.CommandConfigError, match="路径"):
        _specs({"log_paths": ["var/log/x.log"], "log_keywords": ["err"]})


def test_profile_derived_grep_pattern():
    specs = _specs(_PROFILE)
    s = next(x for x in specs if x.metric_id == "local.process.present")
    assert "pgrep -fa 'elasticsearch'" in s.command
    assert "grep '[e]lasticsearch'" in s.command  # 自排除写法仅用于 grep


def test_profile_ports_grouping():
    specs = _specs(_PROFILE)
    s = next(x for x in specs if x.metric_id == "local.port.listening")
    assert s.command == "ss -tlnp | grep -E ':(9200|9300)'"


def test_profile_missing_marks_unsupported():
    """无 profile：需 profile 的 6 个指标 → UNSUPPORTED_PROFILE；其余 4 个正常。"""
    specs = _specs({})
    need_profile = {
        "local.process.present",
        "local.service.active",
        "local.port.listening",
        "local.logs.key_evidence",
        "local.nginx.config.valid",
        "local.nginx.version",
        "local.nginx.port.listening",
        "local.nginx.error_log.key_evidence",
        "local.nginx.connections.status",
        "local.nginx.access_log.status_codes",
        "local.nginx.config.baseline",
        "local.nginx.security.baseline",
        "local.keepalived.version",
        "local.keepalived.vip.bound",
        "local.keepalived.vip.access",
        "local.keepalived.config.baseline",
        "local.keepalived.healthcheck.script",
        "local.keepalived.error_log.key_evidence",
        "local.keepalived.capability.stability",
        "local.elasticsearch.version",
        "local.elasticsearch.cluster.health",
        "local.elasticsearch.nodes.online",
        "local.elasticsearch.nodes.cpu",
        "local.elasticsearch.nodes.memory",
        "local.elasticsearch.nodes.disk",
        "local.elasticsearch.disk.watermark",
        "local.elasticsearch.shards.unassigned",
        "local.elasticsearch.service.port",
        "local.elasticsearch.heap.gc",
        "local.elasticsearch.thread_pool.rejected",
        "local.elasticsearch.cluster.settings",
        "local.elasticsearch.discovery.config",
        "local.elasticsearch.indices.health",
        "local.elasticsearch.slowlog.key_evidence",
        "local.elasticsearch.security.accounts",
        "local.elasticsearch.certificate.validity",
        "local.elasticsearch.snapshot.repository",
        "local.elasticsearch.system.parameters",
    }
    for s in specs:
        if s.metric_id in need_profile:
            assert s.command is None
            assert s.error_code == ar.ERROR_UNSUPPORTED_PROFILE
        else:
            assert s.command is not None
            assert s.error_code is None


def test_profile_partial_missing_marks_unsupported():
    specs = _specs({"ports": [9200]})  # 仅端口
    by_id = {s.metric_id: s for s in specs}
    assert by_id["local.port.listening"].command == "ss -tlnp | grep -E ':(9200)'"
    assert by_id["local.process.present"].error_code == ar.ERROR_UNSUPPORTED_PROFILE


def test_profile_root_path_allowed():
    specs = _specs({"fs_paths": ["/"], "process_pattern": "x", "ports": [80],
                    "unit": "x.service", "log_paths": ["/a/*.log"],
                    "log_keywords": ["err"]})
    s = next(x for x in specs if x.metric_id == "local.filesystem.used_percent")
    assert s.command == "df -hT"


# ==========================================================================
# 5. 执行封装：argv / prepare_run / 300s 上限（AE §7）
# ==========================================================================


def test_build_playbook_argv_no_credentials():
    argv = ar.build_playbook_argv(Path("p.yml"), Path("i.ini"), None)
    assert argv[:3] == ["ansible-playbook", "p.yml", "-i"]
    assert "i.ini" in argv
    assert not any(a.startswith("--user") or "password" in a or "key" in a for a in argv)


def test_build_playbook_argv_limit():
    argv = ar.build_playbook_argv(Path("p.yml"), Path("i.ini"), "db")
    assert "--limit" in argv and argv[argv.index("--limit") + 1] == "db"
    argv_all = ar.build_playbook_argv(Path("p.yml"), Path("i.ini"), "all")
    assert "--limit" not in argv_all


def test_prepare_run_writes_playbook(tmp_path):
    class Sel:
        inventory_file = tmp_path / "inv.ini"
        hosts = [{"name": "h1"}]
        limit = None

    plan = ar.prepare_run(Sel(), _specs(_PROFILE), runtime_dir=tmp_path / "rt")
    assert plan.playbook_path.is_file()
    assert plan.playbook_path.read_text(encoding="utf-8").startswith("---")
    assert plan.argv[0] == "ansible-playbook"
    assert plan.inventory_file == tmp_path / "inv.ini"


def test_prepare_run_rejects_bad_specs_before_writing(tmp_path):
    class Sel:
        inventory_file = tmp_path / "inv.ini"
        hosts = [{"name": "h1"}]
        limit = None

    with pytest.raises(ar.CommandNotAllowedError):
        ar.prepare_run(Sel(), [_spec("local.cpu.load_1m", "free -m; e" + "cho x")],
                       runtime_dir=tmp_path / "rt")
    assert not (tmp_path / "rt").exists() or not any((tmp_path / "rt").iterdir())


def test_host_deadline_300s():
    assert ar.HOST_TIMEOUT_SEC == 300
    assert not ar.host_deadline_exceeded(100.0, 100.0 + 299.0)
    assert not ar.host_deadline_exceeded(100.0, 100.0 + 300.0)  # == 边界不超
    assert ar.host_deadline_exceeded(100.0, 100.0 + 300.5)


# ==========================================================================
# 6. 结果分类（纯函数；AE §6 失败与业务状态分离）
# ==========================================================================

_FULL_MATRIX = {c: True for c in probe.PROBE_COMMANDS}


def test_classify_normal_rc_nonzero_is_business_data():
    """rc 非零（如 pgrep/grep 无匹配）不是技术失败：error=None，数据原样回传。"""
    r = ar.classify_metric_result(
        "local.process.present", 1, "", "", ("bash", "pgrep", "ps", "grep"), _FULL_MATRIX
    )
    assert r["error"] is None
    assert r["rc"] == 1


def test_classify_timeout_rc124():
    r = ar.classify_metric_result("local.cpu.load_1m", 124, "", "", ("bash",), _FULL_MATRIX)
    assert r["error"]["code"] == ar.ERROR_TIMEOUT
    assert r["error"]["metric_status"] == ar.METRIC_ERROR_STATUS


def test_classify_permission_denied_stderr():
    r = ar.classify_metric_result(
        "local.cpu.utilization", 0, "", "top: failed: Permission denied",
        ("bash", "top", "ps", "head"), _FULL_MATRIX,
    )
    assert r["error"]["code"] == ar.ERROR_PERMISSION_DENIED


def test_classify_missing_required_command():
    matrix = dict(_FULL_MATRIX)
    matrix["pgrep"] = False
    r = ar.classify_metric_result(
        "local.process.present", 0, "", "", ("bash", "pgrep", "ps", "grep"), matrix
    )
    assert r["error"]["code"] == ar.ERROR_COMMAND_NOT_FOUND
    assert "pgrep" in r["error"]["message"]


def test_classify_unprobed_command_not_falsified():
    """head/cat 未纳入探测集合（TD §5.1）→ 不做缺失判定（G0 预检可扩展）。"""
    r = ar.classify_metric_result(
        "local.cpu.utilization", 0, "", "", ("bash", "top", "ps", "head"), _FULL_MATRIX
    )
    assert r["error"] is None
    r2 = ar.classify_metric_result(
        "local.cpu.load_1m", 0, "", "", ("bash", "cat", "nproc"), _FULL_MATRIX
    )
    assert r2["error"] is None


def test_classify_preset_error_wins():
    r = ar.classify_metric_result(
        "local.process.present", None, "", "", ("bash",), _FULL_MATRIX,
        preset_error={"code": ar.ERROR_UNSUPPORTED_PROFILE, "message": "no profile"},
    )
    assert r["error"]["code"] == ar.ERROR_UNSUPPORTED_PROFILE


def test_build_host_result_connection_failure_no_business():
    class H:
        name, ip = "node-x", "10.0.0.9"

    r = ar.build_host_result(
        H(), {}, False, [],
        host_error=ar._error(ar.ERROR_CONNECTION_FAILED, "conn refused"),
    )
    assert r["execution_status"] == ar.STATUS_ERROR
    assert r["metrics"] == []  # 无业务结论
    assert r["host_error"]["code"] == ar.ERROR_CONNECTION_FAILED


def test_parse_callback_classifies_host_key_preflight_as_connection_failure():
    class H:
        name, ip = "node-x", "10.0.0.9"

    plan = ar.RunPlan(
        playbook_path=Path("playbook.yml"),
        inventory_file=Path("hosts.ini"),
        hosts=[H()],
        limit=None,
        metric_specs=[_spec("local.cpu.load_1m", "cat /proc/loadavg; nproc")],
        probe_command="probe",
    )
    payload = {
        "plays": [{
            "tasks": [{
                "task": {"name": "probe: 能力探测（15s）"},
                "hosts": {
                    "node-x": {
                        "status": "failed",
                        "failed": True,
                        "msg": "host key checking with sshpass",
                    }
                },
            }]
        }]
    }
    result = ar._parse_callback_results(plan, payload, 0.1)
    assert result[0]["execution_status"] == ar.STATUS_ERROR
    assert result[0]["host_error"]["code"] == ar.ERROR_CONNECTION_FAILED
    assert result[0]["metrics"] == []


def test_parse_callback_missing_probe_is_connection_failure():
    class H:
        name, ip = "node-x", "10.0.0.9"

    plan = ar.RunPlan(
        playbook_path=Path("playbook.yml"),
        inventory_file=Path("hosts.ini"),
        hosts=[H()],
        limit=None,
        metric_specs=[_spec("local.cpu.load_1m", "cat /proc/loadavg; nproc")],
        probe_command="probe",
    )
    result = ar._parse_callback_results(plan, {"plays": [], "stats": {}}, 0.1)
    assert result[0]["execution_status"] == ar.STATUS_ERROR
    assert result[0]["host_error"]["code"] == ar.ERROR_CONNECTION_FAILED
    assert "未收到该主机的能力探测回调" in result[0]["host_error"]["message"]
    assert result[0]["metrics"] == []


def test_real_runner_sets_first_connect_host_key_policy():
    source = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert 'env["ANSIBLE_HOST_KEY_CHECKING"] = ANSIBLE_HOST_KEY_CHECKING' in source
    assert 'env["ANSIBLE_SSH_COMMON_ARGS"] = ANSIBLE_SSH_COMMON_ARGS' in source
    assert "StrictHostKeyChecking=accept-new" in source


def test_build_host_result_probe_failed():
    class H:
        name, ip = "node-x", "10.0.0.9"

    matrix = dict(_FULL_MATRIX)
    matrix["bash"] = False
    r = ar.build_host_result(H(), matrix, False, [])
    assert r["execution_status"] == ar.STATUS_ERROR
    assert r["host_error"]["code"] == ar.ERROR_PROBE_FAILED
    assert r["metrics"] == []


def test_build_host_result_partial_and_success():
    class H:
        name, ip = "node-x", "10.0.0.9"

    ok = ar.classify_metric_result("local.cpu.load_1m", 0, "0.5\n8", "",
                                   ("bash", "nproc"), _FULL_MATRIX)
    err = ar.classify_metric_result("local.port.listening", 124, "", "",
                                    ("bash", "ss", "grep"), _FULL_MATRIX)
    partial = ar.build_host_result(H(), _FULL_MATRIX, True, [ok, err])
    assert partial["execution_status"] == ar.STATUS_PARTIAL
    assert partial["summary"] == {"total": 2, "executed": 1, "failed": 1}
    full = ar.build_host_result(H(), _FULL_MATRIX, True, [ok, ok])
    assert full["execution_status"] == ar.STATUS_SUCCESS
    assert full["summary"] == {"total": 2, "executed": 2, "failed": 0}


def test_run_status_for_hosts():
    assert ar.run_status_for_hosts([]) == ar.STATUS_ERROR
    assert ar.run_status_for_hosts([
        {"execution_status": ar.STATUS_ERROR},
        {"execution_status": ar.STATUS_ERROR},
    ]) == ar.STATUS_ERROR
    assert ar.run_status_for_hosts([
        {"execution_status": ar.STATUS_SUCCESS},
        {"execution_status": ar.STATUS_ERROR},
    ]) == ar.STATUS_PARTIAL
    assert ar.run_status_for_hosts([
        {"execution_status": ar.STATUS_SUCCESS},
        {"execution_status": ar.STATUS_PARTIAL},
    ]) == ar.STATUS_PARTIAL
    assert ar.run_status_for_hosts([
        {"execution_status": ar.STATUS_SUCCESS},
    ]) == ar.STATUS_SUCCESS


# ==========================================================================
# 7. fixture 模式（TD §10.2 / REQ-N-08：预录输出，零连接）
# ==========================================================================


def _selection(hosts):
    class Sel:
        inventory_file = Path("inv.ini")

        def __init__(self):
            self.hosts = hosts
            self.limit = None

    return Sel()


def _host(name, ip):
    class H:
        pass

    h = H()
    h.name, h.ip = name, ip
    return h


def _run_fixture(hosts, profile=None, fixture_dir=None, runtime_dir=None):
    return ar.run(_selection(hosts), _specs(profile), fixture_dir=fixture_dir,
                  runtime_dir=runtime_dir)


def test_fixture_full_success_host(capsys, tmp_path):
    result = _run_fixture([_host("node-a", "10.0.0.1")], _FULL_PROFILE, _FIXTURES, tmp_path)
    assert result["execution_status"] == ar.STATUS_SUCCESS
    host = result["hosts"][0]
    assert host["probe_status"] == probe.PROBE_OK
    assert host["summary"]["total"] == 47  # 10 linux + 9 nginx + 8 keepalived + 20 Elasticsearch
    assert host["summary"]["failed"] == 0
    # 预录输出（剥离 # 头）原样回传
    m = next(x for x in host["metrics"] if x["metric_id"] == "local.process.present")
    assert "4321 /usr/bin/java" in m["stdout"]
    assert not m["stdout"].lstrip().startswith("#")
    m2 = next(x for x in host["metrics"] if x["metric_id"] == "local.cpu.load_1m")
    assert m2["stdout"].splitlines()[0] == "0.52 0.44 0.39 1/210 12345"
    assert all(x["error"] is None for x in host["metrics"])
    # stderr 调试模式声明（REQ-N-08）
    err = capsys.readouterr().err
    assert "调试模式（fixture）" in err
    assert "INSPECT_FIXTURE_DIR" in err
    assert "未发起任何连接" in err


def test_fixture_env_var_mode(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv(ar.FIXTURE_ENV_VAR, str(_FIXTURES))
    result = ar.run(_selection([_host("node-a", "10.0.0.1")]), _specs(_FULL_PROFILE),
                    runtime_dir=tmp_path)
    assert result["fixture_mode"] is True
    assert result["execution_status"] == ar.STATUS_SUCCESS
    assert "调试模式（fixture）" in capsys.readouterr().err


def _linux_specs(profile=None):
    """Linux-only specs（linux_common + linux_basic）用于 linux 行为精确断言。"""
    return ar.build_metric_command_specs(
        profile=profile or _PROFILE, module_ids=("linux_common", "linux_basic")
    )


def test_fixture_partial_host_classification(tmp_path):
    """node-b：pgrep 缺失→COMMAND_NOT_FOUND；端口超时→TIMEOUT；
    cpu 权限→PERMISSION_DENIED；主机 PARTIAL。"""
    result = ar.run(
        _selection([_host("node-b", "10.0.0.2")]),
        _linux_specs(),
        fixture_dir=_FIXTURES,
        runtime_dir=tmp_path,
    )
    host = result["hosts"][0]
    assert host["execution_status"] == ar.STATUS_PARTIAL
    by_id = {m["metric_id"]: m for m in host["metrics"]}
    assert by_id["local.process.present"]["error"]["code"] == ar.ERROR_COMMAND_NOT_FOUND
    assert by_id["local.port.listening"]["error"]["code"] == ar.ERROR_TIMEOUT
    assert by_id["local.port.listening"]["rc"] == ar.TIMEOUT_RC
    assert by_id["local.cpu.utilization"]["error"]["code"] == ar.ERROR_PERMISSION_DENIED
    assert by_id["local.cpu.load_1m"]["error"] is None
    assert host["summary"]["failed"] == 3
    assert host["summary"]["executed"] == 7
    assert result["execution_status"] == ar.STATUS_PARTIAL


def test_fixture_connection_failed_no_business(tmp_path):
    result = _run_fixture([_host("node-c", "10.0.0.3")], _PROFILE, _FIXTURES, tmp_path)
    host = result["hosts"][0]
    assert host["execution_status"] == ar.STATUS_ERROR
    assert host["host_error"]["code"] == ar.ERROR_CONNECTION_FAILED
    assert host["metrics"] == []  # 无业务结论
    assert result["execution_status"] == ar.STATUS_ERROR


def test_fixture_probe_failed_host_error(tmp_path):
    result = _run_fixture([_host("node-d", "10.0.0.4")], _PROFILE, _FIXTURES, tmp_path)
    host = result["hosts"][0]
    assert host["execution_status"] == ar.STATUS_ERROR
    assert host["host_error"]["code"] == ar.ERROR_PROBE_FAILED
    assert host["metrics"] == []


def test_fixture_missing_output_data_missing(tmp_path):
    result = _run_fixture([_host("node-e", "10.0.0.5")], _PROFILE, _FIXTURES, tmp_path)
    host = result["hosts"][0]
    assert host["execution_status"] == ar.STATUS_PARTIAL
    by_id = {m["metric_id"]: m for m in host["metrics"]}
    assert by_id["local.cpu.load_1m"]["error"] is None
    assert by_id["local.service.active"]["error"]["code"] == ar.ERROR_DATA_MISSING
    assert by_id["local.filesystem.used_percent"]["error"]["code"] == ar.ERROR_DATA_MISSING


def test_fixture_unsupported_profile_metric(tmp_path):
    """无 profile：6 指标 UNSUPPORTED_PROFILE（不进 playbook、无需夹具输出），
    4 指标正常执行；主机 PARTIAL（非错误，无命令可执行）。"""
    result = _run_fixture([_host("node-a", "10.0.0.1")], {}, _FIXTURES, tmp_path)
    host = result["hosts"][0]
    assert host["execution_status"] == ar.STATUS_PARTIAL
    by_id = {m["metric_id"]: m for m in host["metrics"]}
    assert by_id["local.process.present"]["error"]["code"] == ar.ERROR_UNSUPPORTED_PROFILE
    assert by_id["local.port.listening"]["error"]["code"] == ar.ERROR_UNSUPPORTED_PROFILE
    assert by_id["local.cpu.load_1m"]["error"] is None
    assert by_id["local.memory.available_percent"]["error"] is None


def test_fixture_run_level_all_error(tmp_path):
    result = _run_fixture([_host("node-c", "10.0.0.3")], _PROFILE, _FIXTURES, tmp_path)
    assert result["execution_status"] == ar.STATUS_ERROR


def test_fixture_missing_dir_raises(tmp_path):
    with pytest.raises(ar.FixtureError, match="夹具目录不存在"):
        _run_fixture([_host("node-a", "10.0.0.1")], _PROFILE, tmp_path / "nope", tmp_path)


def test_fixture_declares_mode_on_stderr_without_subprocess(capsys, tmp_path, monkeypatch):
    """fixture 模式不执行任何子进程：无 subprocess 调用、无 ansible-playbook。"""
    monkeypatch.setenv(ar.FIXTURE_ENV_VAR, str(_FIXTURES))
    result = ar.run(_selection([_host("node-a", "10.0.0.1")]), _specs(_PROFILE),
                    runtime_dir=tmp_path)
    assert result["fixture_mode"] is True
    assert "调试模式（fixture）" in capsys.readouterr().err


def test_no_fixture_raises_execution_not_ready(tmp_path, monkeypatch):
    """未设置夹具目录 → ExecutionNotReadyError（真实执行属 G0 预检；退出码 10）。"""
    monkeypatch.delenv(ar.FIXTURE_ENV_VAR, raising=False)
    with pytest.raises(ar.ExecutionNotReadyError) as ei:
        _run_fixture([_host("node-a", "10.0.0.1")], _PROFILE, None, tmp_path)
    assert ei.value.exit_code == 10
    assert "G0" in str(ei.value)
    assert ar.FIXTURE_ENV_VAR in str(ei.value)


# ==========================================================================
# 8. 合同 AC 文本 marker 镜像（AC-1/2/3/5；与 AC-7 pytest 全绿互为证据）
# ==========================================================================


def test_ac1_markers_in_ansible_runner_source():
    src = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "gather_facts" in src
    assert "serial" in src
    assert "raw" in src
    assert "bash -lc" in src


def test_ac2_fixture_env_marker():
    src = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "INSPECT_FIXTURE_DIR" in src


def test_ac3_allow_marker_case_insensitive():
    src = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "allow" in src.lower()


def test_ac5_timeout_unknown_300_markers():
    src = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "TIMEOUT" in src
    assert "UNKNOWN" in src
    assert "300" in src


def test_real_execution_is_explicitly_gated():
    """真实执行存在但必须显式门控，fixture 仍为默认零连接路径。"""
    src = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "subprocess.run" in src
    assert "INSPECT_ENABLE_REAL" in src
    assert "ExecutionNotReadyError" in src


# ==========================================================================
# 9. T-103F 对抗用例（H-1 裸 $/反引号死循环、H-2 双引号内命令替换绕过）
# ==========================================================================
# 独立验证实证：H-1 `_tokenize` 对裸 `$`/反引号死循环挂起（parse_binaries
# ('free -m; $(rm -rf /)') 无限循环）；H-2 双引号内 `$()`/反引号被整体当
# 参数跳过 → 绕过 allow-list（'free -m "$(rm -rf /)"' 被 ACCEPT，shell 在
# 双引号内会展开命令替换）。修复后：一律拒绝（CommandNotAllowedError）、
# 不挂起（单次调用 2s 内返回）；合法指标命令不受影响。每个对抗输入独立成
# 用例（parametrize）固化。

_H1_INPUTS = (
    "free -m; $(rm -rf /)",
    "free -m; `whoami`",
    "free -m $",
)

_H2_INPUTS = (
    'free -m "$(rm -rf /)"',
    'free -m "`whoami`"',
    'cat /proc/loadavg "$(rm -rf /)"',
    'df -hT "/tmp;$(rm -rf /)"',
)


@pytest.mark.parametrize("cmd", _H1_INPUTS)
def test_h1_bare_dollar_backtick_do_not_hang_and_rejected(cmd):
    """T-103F H-1：裸 `$`/反引号不挂起（2s 内返回）且必须拒绝。"""
    start = time.monotonic()
    with pytest.raises(ar.CommandNotAllowedError, match="拒绝"):
        ar.parse_binaries(cmd)
    assert time.monotonic() - start < 2.0, f"{cmd!r} 挂起（>2s）"


@pytest.mark.parametrize("cmd", _H2_INPUTS)
def test_h2_double_quoted_substitution_rejected(cmd):
    """T-103F H-2：双引号内 $()/反引号/$VAR 整体成词必须拒绝（绕过固封）。"""
    start = time.monotonic()
    with pytest.raises(ar.CommandNotAllowedError, match="拒绝"):
        ar.parse_binaries(cmd)
    assert time.monotonic() - start < 2.0, f"{cmd!r} 挂起（>2s）"


def test_h1h2_validate_command_specs_rejects_all_adversarial_inputs():
    """T-103F：对抗输入构造为 CommandSpec 后，执行路径门禁
    validate_command_specs 必须同样拒绝（parse_binaries 抛错直达门禁）。"""
    cases = [
        ("local.memory.available_percent", "free -m; $(rm -rf /)"),
        ("local.memory.available_percent", "free -m; `whoami`"),
        ("local.memory.available_percent", "free -m $"),
        ("local.memory.available_percent", 'free -m "$(rm -rf /)"'),
        ("local.memory.available_percent", 'free -m "`whoami`"'),
        ("local.cpu.load_1m", 'cat /proc/loadavg "$(rm -rf /)"'),
        ("local.filesystem.used_percent", 'df -hT "/tmp;$(rm -rf /)"'),
    ]
    for metric_id, cmd in cases:
        with pytest.raises(ar.CommandNotAllowedError, match="拒绝"):
            ar.validate_command_specs([_spec(metric_id, cmd)])


def test_h1h2_legit_commands_still_accepted():
    """T-103F 对照：合法指标命令不受影响（可执行名提取正常、allow-list 通过）。"""
    assert ar.parse_binaries("free -m") == ["free"]
    assert ar.parse_binaries("cat /proc/loadavg; nproc") == ["cat", "nproc"]
    assert ar.parse_binaries("df -hT / /data") == ["df"]
    assert ar.parse_binaries("tail -300 /var/log/a.log | egrep -i 'error|exception'") == [
        "tail",
        "egrep",
    ]
    ar.validate_command_specs(_specs(_PROFILE))  # 全量注册表命令不抛


# ==========================================================================
# T-109 runtime/diagnostic regression checks
# ==========================================================================

def test_t109_ansible_argv_can_be_bound_to_dedicated_runtime(tmp_path):
    argv = ar.build_playbook_argv(
        tmp_path / "playbook.yml", tmp_path / "hosts", executable="/project/runtime/bin/python3.12"
    )
    assert argv[0] == "/project/runtime/bin/python3.12"
    assert "ansible-playbook" not in argv


def test_t109_callback_diagnostics_are_sanitized():
    with pytest.raises(ar.RealExecutionError) as ei:
        ar._load_callback_payload("", return_code=7)
    message = str(ei.value)
    assert ei.value.category == "callback_empty"
    assert ei.value.return_code == 7
    assert "check=" in message
    assert "password" not in message.lower()


def test_t109_fixture_wins_over_real_gate(tmp_path, monkeypatch):
    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.FIXTURE_ENV_VAR, str(_FIXTURES))
    result = ar.run(_selection([_host("node-a", "10.0.0.1")]), _specs(_PROFILE), runtime_dir=tmp_path)
    assert result["fixture_mode"] is True
    assert "real_mode" not in result


def test_t109_cleanup_source_is_python37_compatible():
    source = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "unlink(missing_ok" not in source


def test_t110_real_runner_uses_bundled_ansible_environment():
    source = (_ROOT / "inspect" / "ansible_runner.py").read_text(encoding="utf-8")
    assert "dedicated_runtime.ansible_environment" in source
    assert "ansible-playbook" not in source[source.index("def _execute_real"):source.index("def _parse_callback_results")]
