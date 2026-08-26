"""RabbitMQ P0/P1 middleware ownership."""

from .registry import MonitorModule

RABBITMQ_METRIC_IDS = (
    "local.rabbitmq.service.health",
    "local.rabbitmq.node.health",
    "local.rabbitmq.core_ports.health",
    "local.rabbitmq.cluster.nodes",
    "local.rabbitmq.alarm.partition",
    "local.rabbitmq.queue.backlog",
    "local.rabbitmq.connection.pressure",
    "local.rabbitmq.error_log",
    "local.rabbitmq.config.baseline",
    "local.rabbitmq.node.identity",
    "local.rabbitmq.security.permissions",
    "local.rabbitmq.topology",
    "local.rabbitmq.queue.durability",
    "local.rabbitmq.file_descriptor.limits",
    "local.rabbitmq.systemd.unit",
    "local.rabbitmq.log.data.retention",
)

MODULE = MonitorModule("rabbitmq", "RabbitMQ 中间件", RABBITMQ_METRIC_IDS)

__all__ = ["RABBITMQ_METRIC_IDS", "MODULE"]
