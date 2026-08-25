"""Kafka P0/P1 middleware ownership."""

from .registry import MonitorModule

KAFKA_METRIC_IDS = (
    "local.kafka.broker.health",
    "local.kafka.controller.health",
    "local.kafka.under_replicated_partitions",
    "local.kafka.under_min_isr",
)

MODULE = MonitorModule("kafka", "Kafka 中间件", KAFKA_METRIC_IDS)

__all__ = ["KAFKA_METRIC_IDS", "MODULE"]
