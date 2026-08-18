"""Tests for the explicit project-local monitor module registry."""

import pytest

from inspect import metrics
from inspect.modules import ModuleRegistry, MonitorModule, default_registry


def test_default_registry_exposes_named_linux_module_and_all_metrics():
    registry = default_registry()
    modules = list(registry.iter_modules())
    assert [module.module_id for module in modules] == ["linux_common", "linux_basic"]
    assert modules[0].display_name == "Linux 通用 P0"
    assert modules[1].display_name == "Linux 主机基础指标"
    assert registry.get("linux_basic").metric_ids == (
        "local.cpu.utilization",
        "local.cpu.load_1m",
        "local.memory.available_percent",
        "local.swap.used_percent",
        "local.filesystem.used_percent",
        "local.filesystem.inode_used_percent",
    )
    assert registry.metric_ids() == tuple(item["metric_id"] for item in metrics.iter_metrics())
    assert len(registry.metric_definitions()) == metrics.count_metrics()


def test_registry_rejects_duplicate_module_and_metric_ownership():
    registry = ModuleRegistry()
    module = MonitorModule("demo", "Demo", ("local.cpu.load_1m",))
    registry.register(module)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(module)
    with pytest.raises(ValueError, match="already owned"):
        registry.register(MonitorModule("demo2", "Demo 2", ("local.cpu.load_1m",)))


def test_registry_rejects_unknown_metric_ids():
    with pytest.raises(ValueError, match="unknown metric"):
        ModuleRegistry().register(MonitorModule("bad", "Bad", ("local.nope",)))
