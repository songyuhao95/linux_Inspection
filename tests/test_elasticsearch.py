from pathlib import Path

from inspect import ansible_runner as ar
from inspect import config
from inspect import normalize
from inspect.modules import default_registry, middleware_module_ids


def test_elasticsearch_module_registered_and_baseline_loaded():
    module = default_registry().get("elasticsearch")
    assert module is not None
    assert len(module.metric_ids) == 20
    assert "elasticsearch" in middleware_module_ids()
    resolved = config.build_resolved_thresholds()
    assert set(module.metric_ids).issubset(resolved)


def test_elasticsearch_parsers_compute_numeric_values():
    health = normalize.parse_elasticsearch_cluster_health(
        '{"status":"green","number_of_nodes":3,"active_shards_percent_as_number":100}\n'
        "INSPECT_ELASTICSEARCH_HTTP_STATUS=200"
    )
    assert health["status"] == "green"
    assert health["nodes"] == 3

    nodes = normalize.parse_elasticsearch_nodes_cpu(
        "name ip cpu load_1m load_5m load_15m\n"
        "es-01 192.0.2.101 92 1 1 1\n"
        "INSPECT_ELASTICSEARCH_HTTP_STATUS=200"
    )
    assert nodes["max_cpu"] == 92
    assert normalize.JUDGERS["local.elasticsearch.nodes.cpu"](
        nodes, config.build_resolved_thresholds()["local.elasticsearch.nodes.cpu"], {}
    )["status"] == "CRIT"


def test_elasticsearch_api_auth_failure_is_not_default_pass():
    try:
        normalize.parse_elasticsearch_cluster_health(
            "{\"error\":\"unauthorized\"}\nINSPECT_ELASTICSEARCH_HTTP_STATUS=401"
        )
    except normalize.ParseError as exc:
        assert "HTTP 401" in str(exc)
    else:
        raise AssertionError("401 must not be interpreted as a healthy cluster")


def test_elasticsearch_process_selection_skips_non_whitelisted_host():
    results = [
        {"metric_id": "local.elasticsearch.process.present", "error": None, "rc": 1, "stdout": ""},
        {"metric_id": "local.elasticsearch.version", "error": None, "rc": 0, "stdout": "Version: 8.17.0"},
        {"metric_id": "local.cpu.utilization", "error": None, "rc": 0, "stdout": ""},
    ]
    selected = ar.select_elasticsearch_metrics(results, host_ip="192.0.2.10", elasticsearch_whitelist=[])
    assert [item["metric_id"] for item in selected] == ["local.cpu.utilization"]
    selected = ar.select_elasticsearch_metrics(results, host_ip="192.0.2.10", elasticsearch_whitelist=["192.0.2.10"])
    assert [item["metric_id"] for item in selected] == ["local.cpu.utilization", "local.elasticsearch.process.present"]


def test_elasticsearch_fixture_commands_are_generated_from_profile():
    profile = config.load_inspect_conf()
    specs = ar.build_metric_command_specs(module_ids=("elasticsearch",), profile=profile)
    assert len(specs) == 20
    assert any("_cluster/health" in (spec.command or "") for spec in specs)
    assert all(spec.trusted_generated_shell or spec.metric_id.endswith("process.present") for spec in specs)
    ar.validate_command_specs(specs)

    system = next(x for x in specs if x.metric_id == "local.elasticsearch.system.parameters")
    assert "/proc/$es_pid/limits" in system.command
    assert "su -" not in system.command


def test_elasticsearch_api_credentials_use_private_config_and_cacert():
    profile = config.load_inspect_conf()
    profile["elasticsearch_cacert"] = ["/opt/elasticsearch/conf/certs/http_ca.crt"]
    profile["elasticsearch_api_user"] = ["elastic"]
    profile["elasticsearch_api_password"] = ["unit-test@password"]
    profile["elasticsearch_cert"] = []

    specs = ar.build_metric_command_specs(
        module_ids=("elasticsearch",), profile=profile
    )
    health = next(
        spec for spec in specs if spec.metric_id == "local.elasticsearch.cluster.health"
    )
    assert "--cacert" in health.command
    assert "INSPECT_ES_API_USER" in health.command
    assert "INSPECT_ES_API_PASSWORD" in health.command
    assert "unit-test@password" not in health.command
    assert health.module == "ansible.builtin.shell"
    assert health.task_environment == {
        "INSPECT_ES_API_USER": "elastic",
        "INSPECT_ES_API_PASSWORD": "unit-test@password",
    }

    certificate = next(
        spec for spec in specs
        if spec.metric_id == "local.elasticsearch.certificate.validity"
    )
    assert "es_cert" in certificate.command
    assert "es_cacert" in certificate.command

    playbook = ar.generate_playbook([health])
    assert "ansible.builtin.shell:" in playbook
    assert "environment:" in playbook
    assert "INSPECT_ES_API_PASSWORD: 'unit-test@password'" in playbook


def test_elasticsearch_system_parameters_parse_process_limits():
    parsed = normalize.parse_elasticsearch_system_parameters(
        "ES_MAX_MAP_COUNT=262144\n"
        "Swap: 8192 0 8192\n"
        "ES_ULIMIT_NOFILE=65535\n"
        "ES_ULIMIT_NPROC=4096\n"
        "ES_ULIMIT_MEMLOCK=unlimited\n"
    )
    assert parsed["max_map_count"] == 262144
    assert parsed["nofile"] == 65535
    assert parsed["nproc"] == 4096
    assert parsed["memlock"] == "unlimited"
