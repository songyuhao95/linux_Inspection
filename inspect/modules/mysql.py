"""MySQL P0/P1 middleware ownership."""

from .registry import MonitorModule

MYSQL_METRIC_IDS = (
    "local.mysql.service.health",
    "local.mysql.login.version",
    "local.mysql.role.gtid",
    "local.mysql.replica.threads",
    "local.mysql.replication.lag",
    "local.mysql.connection.pressure",
    "local.mysql.binlog.relaylog",
    "local.mysql.error_log.key_evidence",
    "local.mysql.slow_query.key_evidence",
    "local.mysql.innodb.waits",
    "local.mysql.buffer_pool.hit_ratio",
    "local.mysql.sql.digest",
    "local.mysql.config.baseline",
    "local.mysql.security.accounts",
    "local.mysql.backup.status",
)

MODULE = MonitorModule("mysql", "MySQL 中间件", MYSQL_METRIC_IDS)

__all__ = ["MYSQL_METRIC_IDS", "MODULE"]
