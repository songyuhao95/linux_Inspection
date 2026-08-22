"""Built-in Linux host basics monitor module.

This module owns profile-free host health metrics.  It is intentionally
separate from ``linux_common`` so future middleware adapters can be added
without changing the local/remote execution or JSON fact-source pipeline.
"""

from .registry import MonitorModule

BASIC_METRIC_IDS = (
    "local.cpu.utilization",
    "local.cpu.load_1m",
    "local.memory.available_percent",
    "local.swap.used_percent",
    "local.filesystem.used_percent",
    "local.filesystem.inode_used_percent",
)

MODULE = MonitorModule(
    module_id="linux_basic",
    display_name="Linux 主机基础指标",
    metric_ids=BASIC_METRIC_IDS,
)

__all__ = ["BASIC_METRIC_IDS", "MODULE"]
