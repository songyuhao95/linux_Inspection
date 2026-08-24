"""Nacos P0/P1 middleware ownership."""

from .registry import MonitorModule

NACOS_METRIC_IDS = (
    "local.nacos.service.health",
    "local.nacos.core_ports.health",
    "local.nacos.http.health",
    "local.nacos.cluster.nodes",
    "local.nacos.mysql.connectivity",
    "local.nacos.error_log",
)

MODULE = MonitorModule("nacos", "Nacos 中间件", NACOS_METRIC_IDS)

__all__ = ["NACOS_METRIC_IDS", "MODULE"]
