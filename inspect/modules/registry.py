"""Explicit registry for inspect monitor modules.

The registry is the stable extension point for future middleware adapters.
Execution code consumes metric definitions from here instead of importing a
flat global list directly.  Registration is explicit by design: unreviewed
files cannot silently become executable monitoring code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Sequence

from inspect import metrics as metrics_catalog


@dataclass(frozen=True)
class MonitorModule:
    """One independently identifiable group of metrics."""

    module_id: str
    display_name: str
    metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.module_id or not self.display_name:
            raise ValueError("module_id and display_name are required")
        if not self.metric_ids:
            raise ValueError(f"module {self.module_id!r} must register metrics")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError(f"module {self.module_id!r} contains duplicate metric IDs")


class ModuleRegistry:
    """Deterministic registry with duplicate and unknown-ID protection."""

    def __init__(self, metric_catalog=metrics_catalog) -> None:
        self._metric_catalog = metric_catalog
        self._modules: Dict[str, MonitorModule] = {}

    def register(self, module: MonitorModule) -> MonitorModule:
        if module.module_id in self._modules:
            raise ValueError(f"monitor module already registered: {module.module_id}")
        for metric_id in module.metric_ids:
            if self._metric_catalog.get_metric(metric_id) is None:
                raise ValueError(
                    f"monitor module {module.module_id!r} references unknown metric: {metric_id}"
                )
        existing = {
            metric_id
            for registered in self._modules.values()
            for metric_id in registered.metric_ids
        }
        overlap = sorted(existing.intersection(module.metric_ids))
        if overlap:
            raise ValueError(f"metric IDs already owned by another module: {overlap}")
        self._modules[module.module_id] = module
        return module

    def get(self, module_id: str) -> MonitorModule | None:
        return self._modules.get(module_id)

    def iter_modules(self) -> Iterator[MonitorModule]:
        yield from self._modules.values()

    def module_for_metric(self, metric_id: str) -> MonitorModule | None:
        return next(
            (module for module in self._modules.values() if metric_id in module.metric_ids),
            None,
        )

    def iter_metric_definitions(self) -> Iterator[dict]:
        # Preserve catalog order in the JSON fact source while ownership is
        # split across independently registered monitor modules.
        owned = {
            metric_id
            for module in self._modules.values()
            for metric_id in module.metric_ids
        }
        for metric in self._metric_catalog.iter_metrics():
            if metric["metric_id"] in owned:
                yield metric

    def metric_definitions(self) -> List[dict]:
        return list(self.iter_metric_definitions())

    def metric_ids(self) -> tuple[str, ...]:
        return tuple(metric["metric_id"] for metric in self.iter_metric_definitions())


def _build_default_registry() -> ModuleRegistry:
    # Import after the registry classes exist so each built-in module remains
    # a separate, reviewable registration file.
    from .linux_basic import MODULE as BASIC_MODULE
    from .linux_common import MODULE as COMMON_MODULE

    registry = ModuleRegistry()
    registry.register(COMMON_MODULE)
    registry.register(BASIC_MODULE)
    return registry


DEFAULT_REGISTRY = _build_default_registry()
# Function form keeps the call site readable and leaves room for a future
# configured registry without changing the runner API.
def default_registry() -> ModuleRegistry:
    return DEFAULT_REGISTRY


__all__ = [
    "DEFAULT_REGISTRY",
    "ModuleRegistry",
    "MonitorModule",
    "default_registry",
]
