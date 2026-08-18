"""Project-local monitor module registry.

A monitor module is an explicit, reviewable registration unit.  Adding a file
under ``inspect/modules`` is intentionally not enough to make it executable;
the module must be registered so the execution plan remains deterministic and
allow-list validation continues to be the single command-safety boundary.
"""

from .registry import (
    DEFAULT_COLLECTION_MODULE_IDS,
    DEFAULT_REGISTRY,
    ModuleRegistry,
    MonitorModule,
    default_registry,
)

__all__ = [
    "DEFAULT_COLLECTION_MODULE_IDS",
    "DEFAULT_REGISTRY",
    "ModuleRegistry",
    "MonitorModule",
    "default_registry",
]
