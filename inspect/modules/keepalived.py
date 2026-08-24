"""Built-in Keepalived middleware monitor module (keepalived-p0-v1).

Keepalived is process-discovered in the same way as Nginx.  A host without a
running Keepalived process is skipped unless its address is listed in
``inspect.conf`` as ``keepalived_whitelist``; a whitelisted missing process is
reported as CRIT so an expected HA node cannot silently disappear.
"""

from .registry import MonitorModule

KEEPALIVED_METRIC_IDS = (
    "local.keepalived.process.present",
    "local.keepalived.version",
    "local.keepalived.vip.bound",
    "local.keepalived.vip.access",
    "local.keepalived.config.baseline",
    "local.keepalived.healthcheck.script",
    "local.keepalived.error_log.key_evidence",
    "local.keepalived.capability.stability",
    "local.keepalived.vip.present",
    "local.keepalived.vrrp.role",
    "local.keepalived.health_check.status",
)

MODULE = MonitorModule(
    module_id="keepalived",
    display_name="Keepalived 中间件",
    metric_ids=KEEPALIVED_METRIC_IDS,
)

__all__ = ["MODULE", "KEEPALIVED_METRIC_IDS"]
