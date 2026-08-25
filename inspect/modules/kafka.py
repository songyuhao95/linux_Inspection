"""Kafka P0/P1 middleware ownership."""

from .registry import MonitorModule

KAFKA_METRIC_IDS = (
    "local.kafka.broker.health",
    "local.kafka.controller.health",
    "local.kafka.broker.registration",
    "local.kafka.under_replicated_partitions",
    "local.kafka.under_min_isr",
    "local.kafka.topic.replica_distribution",
    "local.kafka.consumer.lag",
    "local.kafka.error_log",
    "local.kafka.config.baseline",
    "local.kafka.ssl.certificate",
    "local.kafka.system.parameters",
)

MODULE = MonitorModule("kafka", "Kafka 中间件", KAFKA_METRIC_IDS)

__all__ = ["KAFKA_METRIC_IDS", "MODULE"]
