"""Redis P0/P1 middleware ownership."""

from .registry import MonitorModule

REDIS_METRIC_IDS = (
    "local.redis.service.health",
    "local.redis.ping.version",
    "local.redis.core_ports.health",
    "local.redis.replication.health",
    "local.redis.sentinel.health",
    "local.redis.cluster.health",
    "local.redis.memory.pressure",
    "local.redis.persistence.health",
    "local.redis.error_log",
    "local.redis.config.baseline",
    "local.redis.security.baseline",
    "local.redis.slow_query",
    "local.redis.clients.pressure",
    "local.redis.keyspace.stats",
    "local.redis.system.parameters",
    "local.redis.service.unit",
    "local.redis.log.data.retention",
)

MODULE = MonitorModule("redis", "Redis 中间件", REDIS_METRIC_IDS)

__all__ = ["REDIS_METRIC_IDS", "MODULE"]
