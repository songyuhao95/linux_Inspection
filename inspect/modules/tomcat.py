"""Tomcat P0/P1 middleware ownership."""

from .registry import MonitorModule

TOMCAT_METRIC_IDS = (
    "local.tomcat.service.health",
    "local.tomcat.http.health",
    "local.tomcat.access_log.errors",
    "local.tomcat.jvm.memory",
    "local.tomcat.thread_pool.pressure",
    "local.tomcat.security.baseline",
)

MODULE = MonitorModule("tomcat", "Tomcat 中间件", TOMCAT_METRIC_IDS)

__all__ = ["TOMCAT_METRIC_IDS", "MODULE"]
