"""Tomcat P0/P1 middleware ownership."""

from .registry import MonitorModule

TOMCAT_METRIC_IDS = (
    "local.tomcat.service.health",
    "local.tomcat.http.health",
    "local.tomcat.http.reachability",
    "local.tomcat.access_log.errors",
    "local.tomcat.error_log.key_evidence",
    "local.tomcat.jvm.memory",
    "local.tomcat.thread_pool.pressure",
    "local.tomcat.security.baseline",
    "local.tomcat.default_apps",
    "local.tomcat.java.environment",
    "local.tomcat.access_log.5xx",
    "local.tomcat.connection.status",
    "local.tomcat.log.rotation",
    "local.tomcat.jvm.crash_files",
    "local.tomcat.port.isolation",
)

MODULE = MonitorModule("tomcat", "Tomcat 中间件", TOMCAT_METRIC_IDS)

__all__ = ["TOMCAT_METRIC_IDS", "MODULE"]
