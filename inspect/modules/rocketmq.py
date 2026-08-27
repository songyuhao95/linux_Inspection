"""RocketMQ P0/P1 middleware ownership."""

from .registry import MonitorModule

ROCKETMQ_METRIC_IDS = (
    "local.rocketmq.java.environment",
    "local.rocketmq.namesrv.health",
    "local.rocketmq.broker.health",
    "local.rocketmq.core_ports.health",
    "local.rocketmq.cluster.registration",
    "local.rocketmq.controller.sync_set",
    "local.rocketmq.consumer.lag",
    "local.rocketmq.jvm.memory",
    "local.rocketmq.storage.health",
    "local.rocketmq.error_log",
    "local.rocketmq.config.baseline",
    "local.rocketmq.topic.route",
    "local.rocketmq.consumer.groups",
    "local.rocketmq.broker.runtime",
    "local.rocketmq.jvm.gc",
    "local.rocketmq.system.parameters",
    "local.rocketmq.systemd.unit",
    "local.rocketmq.log.data.retention",
)

MODULE = MonitorModule("rocketmq", "RocketMQ 中间件", ROCKETMQ_METRIC_IDS)

__all__ = ["ROCKETMQ_METRIC_IDS", "MODULE"]
