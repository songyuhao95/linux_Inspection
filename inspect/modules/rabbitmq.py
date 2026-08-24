"""RabbitMQ P0/P1 middleware ownership."""

from .registry import MonitorModule

RABBITMQ_METRIC_IDS = (
    "local.rabbitmq.service.health",
    "local.rabbitmq.node.health",
    "local.rabbitmq.cluster.nodes",
    "local.rabbitmq.alarm.partition",
    "local.rabbitmq.queue.backlog",
    "local.rabbitmq.connection.pressure",
)

MODULE = MonitorModule("rabbitmq", "RabbitMQ 中间件", RABBITMQ_METRIC_IDS)

__all__ = ["RABBITMQ_METRIC_IDS", "MODULE"]
