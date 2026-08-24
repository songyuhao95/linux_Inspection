"""RocketMQ P0/P1 middleware ownership."""

from .registry import MonitorModule

ROCKETMQ_METRIC_IDS = (
    "local.rocketmq.namesrv.health",
    "local.rocketmq.broker.health",
    "local.rocketmq.core_ports.health",
    "local.rocketmq.cluster.registration",
    "local.rocketmq.controller.sync_set",
    "local.rocketmq.consumer.lag",
)

MODULE = MonitorModule("rocketmq", "RocketMQ 中间件", ROCKETMQ_METRIC_IDS)

__all__ = ["ROCKETMQ_METRIC_IDS", "MODULE"]
