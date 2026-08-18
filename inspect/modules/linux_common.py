"""The built-in Linux profile-dependent common monitor module."""

from .registry import MonitorModule

PROFILE_METRIC_IDS = (
    "local.process.present",
    "local.service.active",
    "local.port.listening",
    "local.logs.key_evidence",
)

MODULE = MonitorModule(
    module_id="linux_common",
    display_name="Linux 通用 P0",
    metric_ids=PROFILE_METRIC_IDS,
)

__all__ = ["MODULE", "PROFILE_METRIC_IDS"]
