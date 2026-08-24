"""Redis P0/P1 middleware ownership."""

from .registry import MonitorModule

REDIS_METRIC_IDS = (
    "local.redis.service.health",
    "local.redis.ping.version",
    "local.redis.replication.health",
    "local.redis.sentinel.health",
    "local.redis.cluster.health",
    "local.redis.persistence.health",
)

MODULE = MonitorModule("redis", "Redis 中间件", REDIS_METRIC_IDS)

__all__ = ["REDIS_METRIC_IDS", "MODULE"]
