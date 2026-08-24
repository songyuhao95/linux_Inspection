"""MySQL P0/P1 middleware ownership."""

from .registry import MonitorModule

MYSQL_METRIC_IDS = (
    "local.mysql.service.health",
    "local.mysql.login.version",
    "local.mysql.role.gtid",
    "local.mysql.replica.threads",
    "local.mysql.replication.lag",
    "local.mysql.connection.pressure",
)

MODULE = MonitorModule("mysql", "MySQL 中间件", MYSQL_METRIC_IDS)

__all__ = ["MYSQL_METRIC_IDS", "MODULE"]
