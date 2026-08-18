"""The built-in Linux common monitor module.

This module exists as a named registration unit so future middleware modules
can follow the same shape without changing the CLI or execution pipeline.
"""

from inspect import metrics as metrics_catalog

from .registry import MonitorModule

MODULE = MonitorModule(
    module_id="linux_common",
    display_name="Linux 通用 P0",
    metric_ids=tuple(metric["metric_id"] for metric in metrics_catalog.iter_metrics()),
)

__all__ = ["MODULE"]
