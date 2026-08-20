"""Keepalived 中间件模块测试（keepalived-p0-v1）。"""

from __future__ import annotations

from pathlib import Path

from inspect import ansible_runner as ar
from inspect import config as cfg
from inspect import metrics
from inspect import normalize as norm
from inspect.modules import default_registry, middleware_module_ids


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "raw"
KEEPALIVED_IDS = (
    "local.keepalived.process.present",
    "local.keepalived.version",
    "local.keepalived.vip.bound",
    "local.keepalived.vip.access",
    "local.keepalived.config.baseline",
    "local.keepalived.healthcheck.script",
    "local.keepalived.error_log.key_evidence",
    "local.keepalived.capability.stability",
)


def _host(name: str, ip: str):
    class Host:
        pass

    host = Host()
    host.name, host.ip = name, ip
    return host


def _selection(hosts):
    class Selection:
        inventory_file = Path("inventory/hosts.local.ini")
        limit = None
        kind = "fixture"

        def __init__(self):
            self.hosts = hosts

    return Selection()


def _metric_result(metric_id: str, stdout: str, rc: int = 0):
    return {"metric_id": metric_id, "rc": rc, "stdout": stdout, "stderr": "", "error": None}


def test_keepalived_module_registered_and_catalogued():
    module = default_registry().get("keepalived")
    assert module is not None
    assert module.metric_ids == KEEPALIVED_IDS
    assert middleware_module_ids() == ("nginx", "keepalived")
    assert tuple(m["metric_id"] for m in metrics.KEEPALIVED_METRICS) == KEEPALIVED_IDS


def test_keepalived_thresholds_resolve():
    resolved = cfg.build_resolved_thresholds()
    assert set(KEEPALIVED_IDS).issubset(resolved)
    assert all(resolved[mid]["version"] == "keepalived-p0-v1" for mid in KEEPALIVED_IDS)


def test_keepalived_process_selection_skips_non_ha_host_and_crits_whitelist():
    results = [
        _metric_result("local.cpu.utilization", "10"),
        _metric_result("local.keepalived.process.present", ""),
        _metric_result("local.keepalived.config.baseline", "config"),
    ]
    skipped = ar.select_keepalived_metrics(results, host_ip="192.0.2.10", keepalived_whitelist=[])
    assert [item["metric_id"] for item in skipped] == ["local.cpu.utilization"]
    crit = ar.select_keepalived_metrics(
        results, host_ip="192.0.2.10", keepalived_whitelist=["192.0.2.10"]
    )
    assert [item["metric_id"] for item in crit] == [
        "local.cpu.utilization", "local.keepalived.process.present"
    ]


def test_keepalived_parsers_and_judgement():
    assert norm.parse_keepalived_version("Keepalived v2.2.8\n")["version"] == "keepalived/2.2.8"
    vip = norm.parse_keepalived_vip_bound(
        "CONFIG_STATE=MASTER\nCONFIG_VIP=192.0.2.253/24\neth0 UP 192.0.2.253/24\n"
    )
    assert vip["bound"] is True
    access = norm.parse_keepalived_vip_access("CONFIG_ACCESS=192.0.2.253:8010\nHTTP/1.1 200 OK\n")
    assert access["http_status"] == 200
    log = norm.parse_keepalived_error_log(
        "INSPECT_KEEPALIVED_LOG=/var/log/keepalived.log\nEntering FAULT\n"
    )
    assert log["fault_count"] == 1


def test_keepalived_fixture_full_pipeline(tmp_path):
    profile = cfg.load_inspect_conf()
    specs = ar.build_metric_command_specs(
        module_ids=("linux_basic", "keepalived"), profile=profile
    )
    result = ar.run(
        _selection([_host("node-a", "192.0.2.101")]),
        specs,
        fixture_dir=FIXTURES,
        runtime_dir=tmp_path,
        keepalived_whitelist=["192.0.2.101"],
    )
    assert result["execution_status"] == ar.STATUS_SUCCESS
    raw_host = result["hosts"][0]
    assert {item["metric_id"] for item in raw_host["metrics"]} == set(
        [
            "local.cpu.utilization",
            "local.cpu.load_1m",
            "local.memory.available_percent",
            "local.swap.used_percent",
            "local.filesystem.used_percent",
            "local.filesystem.inode_used_percent",
        ] + list(KEEPALIVED_IDS)
    )
    normalized = norm.normalize_host_result(
        raw_host,
        run_id="run-keepalived-test",
        inspection_id="insp-20260820120000-node-a",
        collected_at="2026-08-20T12:00:00+08:00",
        profile=profile,
        resolved_thresholds=cfg.build_resolved_thresholds(),
        inventory_source="fixture",
    )
    by_id = {metric["metric_id"]: metric for metric in normalized["metrics"]}
    assert by_id["local.keepalived.process.present"]["status"] == "OK"
    assert by_id["local.keepalived.vip.bound"]["status"] == "OK"
    assert by_id["local.keepalived.healthcheck.script"]["status"] == "OK"
