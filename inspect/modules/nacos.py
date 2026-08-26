"""Nacos P0/P1 middleware ownership."""

from .registry import MonitorModule

NACOS_METRIC_IDS = (
    "local.nacos.service.health",
    "local.nacos.core_ports.health",
    "local.nacos.http.health",
    "local.nacos.cluster.config",
    "local.nacos.cluster.nodes",
    "local.nacos.mysql.connectivity",
    "local.nacos.error_log",
    "local.nacos.auth.config",
    "local.nacos.http.errors",
    "local.nacos.jvm.parameters",
    "local.nacos.thread.fd.pressure",
    "local.nacos.config.baseline",
    "local.nacos.log.data.retention",
    "local.nacos.metrics.collection",
    "local.nacos.database.errors",
    "local.nacos.system.parameters",
)

MODULE = MonitorModule("nacos", "Nacos 中间件", NACOS_METRIC_IDS)

__all__ = ["NACOS_METRIC_IDS", "MODULE"]
