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

    def iter_metric_definitions(
        self, module_ids: Sequence[str] | None = None
    ) -> Iterator[dict]:
        """Iterate metric definitions owned by selected modules.

        ``module_ids=None`` preserves the complete registered catalog for
        read-only discovery.  Execution callers can pass an explicit module
        list so profile-dependent middleware metrics are not implicitly
        collected when no middleware was selected.
        """
        selected = (
            tuple(self._modules)
            if module_ids is None
            else tuple(module_ids)
        )
        unknown = [module_id for module_id in selected if module_id not in self._modules]
        if unknown:
            raise ValueError(f"unknown monitor module(s): {unknown}")
        owned = {
            metric_id
            for module_id in selected
            for metric_id in self._modules[module_id].metric_ids
        }
        # Preserve catalog order in the JSON fact source while ownership is
        # split across independently registered monitor modules.
        for metric in self._metric_catalog.iter_metrics():
            if metric["metric_id"] in owned:
                yield metric

    def metric_definitions(self, module_ids: Sequence[str] | None = None) -> List[dict]:
        return list(self.iter_metric_definitions(module_ids))

    def metric_ids(self, module_ids: Sequence[str] | None = None) -> tuple[str, ...]:
        return tuple(
            metric["metric_id"] for metric in self.iter_metric_definitions(module_ids)
        )


def _build_default_registry() -> ModuleRegistry:
    # Import after the registry classes exist so each built-in module remains
    # a separate, reviewable registration file.
    from .linux_basic import MODULE as BASIC_MODULE
    from .linux_common import MODULE as COMMON_MODULE
    from .nginx import MODULE as NGINX_MODULE

    registry = ModuleRegistry()
    registry.register(COMMON_MODULE)
    registry.register(BASIC_MODULE)
    registry.register(NGINX_MODULE)
    return registry


DEFAULT_REGISTRY = _build_default_registry()

# Only profile-free host basics are collected until a caller explicitly
# selects a middleware module.  This keeps an unspecified inspection focused
# and avoids manufacturing UNSUPPORTED_PROFILE results for future adapters.
DEFAULT_COLLECTION_MODULE_IDS = ("linux_basic",)

# Non-Linux middleware modules (e.g. "nginx").  The CLI default collects
# ``linux_basic`` plus every middleware module; ``--nginx`` narrows the
# middleware selection to Nginx only.  New middleware adapters register here
# implicitly by being added to the default registry.
_MIDDLEWARE_EXCLUDED = frozenset({"linux_basic", "linux_common"})


def middleware_module_ids(registry: ModuleRegistry | None = None) -> tuple[str, ...]:
    """Registered middleware module IDs (everything outside Linux host basics)."""
    reg = registry if registry is not None else DEFAULT_REGISTRY
    return tuple(
        module.module_id
        for module in reg.iter_modules()
        if module.module_id not in _MIDDLEWARE_EXCLUDED
    )


# Function form keeps the call site readable and leaves room for a future
# configured registry without changing the runner API.
def default_registry() -> ModuleRegistry:
    return DEFAULT_REGISTRY


__all__ = [
    "DEFAULT_COLLECTION_MODULE_IDS",
    "DEFAULT_REGISTRY",
    "ModuleRegistry",
    "MonitorModule",
    "default_registry",
    "middleware_module_ids",
]
