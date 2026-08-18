from pathlib import Path

from inspect import ansible_runner as runner_mod
from inspect import fact_source, local_runner, normalize
from inspect.inventory import HostEntry, HostSelection

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "raw"


def _local_selection(host_name="node-a"):
    return HostSelection(
        kind="local",
        inventory_file=ROOT / ".runtime" / "unused-local.ini",
        hosts=[HostEntry(name=host_name, ip="127.0.0.1")],
    )


def test_linux_basic_is_explicitly_registered_and_profile_free():
    module = runner_mod.default_registry().get("linux_basic")
    assert module is not None
    assert module.metric_ids == (
        "local.cpu.utilization",
        "local.cpu.load_1m",
        "local.memory.available_percent",
        "local.swap.used_percent",
        "local.filesystem.used_percent",
        "local.filesystem.inode_used_percent",
    )
    specs = {spec.metric_id: spec for spec in runner_mod.build_metric_command_specs()}
    for metric_id in module.metric_ids:
        assert specs[metric_id].command is not None
        assert specs[metric_id].error_code is None


def test_default_collection_excludes_unselected_middleware_metrics():
    specs = runner_mod.build_metric_command_specs()
    assert tuple(spec.metric_id for spec in specs) == runner_mod.default_registry().metric_ids(
        ("linux_basic",)
    )
    assert all(spec.error_code is None for spec in specs)


def test_linux_basic_uses_interval_cpu_and_all_filesystems():
    specs = {spec.metric_id: spec for spec in runner_mod.build_metric_command_specs()}
    assert "top -bn2 -d 1" in specs["local.cpu.utilization"].command
    assert "grep 'Cpu(s)' | tail -1" in specs["local.cpu.utilization"].command
    assert specs["local.filesystem.used_percent"].command == "df -hT"
    assert specs["local.filesystem.inode_used_percent"].command == "df -i"


def test_profile_dependent_module_stays_unknown_when_explicitly_selected():
    specs = {
        spec.metric_id: spec
        for spec in runner_mod.build_metric_command_specs(
            profile={}, module_ids=("linux_common",)
        )
    }
    for metric_id in runner_mod.default_registry().get("linux_common").metric_ids:
        assert specs[metric_id].command is None
        assert specs[metric_id].error_code == runner_mod.ERROR_UNSUPPORTED_PROFILE


def test_linux_basic_results_are_written_as_valid_host_json(tmp_path):
    run_result = local_runner.run_local(
        _local_selection(),
        runner_mod.build_metric_command_specs(),
        fixture_dir=FIXTURES,
        runtime_dir=tmp_path / "runtime",
    )
    normalized = normalize.normalize_run_results(
        run_result,
        run_id="run-20260818-basic",
        inspection_id="insp-20260818120000-node-a",
        collected_at="2026-08-18T12:00:00+08:00",
        profile=None,
        product_profiles=[],
        inventory_source="local",
        meta=None,
    )
    written = fact_source.write_inspection(
        tmp_path / "out",
        "run-20260818-basic",
        "insp-20260818120000-node-a",
        normalized["documents"],
        normalized["host_errors"],
    )
    doc = fact_source.read_host_result(Path(written["entries"][0]["file"]))
    by_id = {metric["metric_id"]: metric for metric in doc["metrics"]}
    assert set(runner_mod.default_registry().get("linux_basic").metric_ids).issubset(by_id)
    assert by_id["local.filesystem.used_percent"]["error"] is None
    assert by_id["local.filesystem.inode_used_percent"]["error"] is None
    assert doc["execution_status"] == "SUCCESS"
    summary = doc["execution_summary"]
    assert summary["total_metrics"] == 6
    assert summary["unknown"] == 0
    assert summary["executed"] == 6
    assert summary["failed"] == 0
    assert summary["ok"] + summary["warn"] + summary["crit"] == 6
    assert not any(
        metric["metric_id"] in runner_mod.default_registry().get("linux_common").metric_ids
        for metric in doc["metrics"]
    )
