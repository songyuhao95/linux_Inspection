"""Standalone ZooKeeper P0/P1 middleware ownership."""

from .registry import MonitorModule

ZOOKEEPER_METRIC_IDS = (
    "local.zookeeper.node.health",
    "local.zookeeper.ports.health",
    "local.zookeeper.error_log",
    "local.zookeeper.mntr.health",
    "local.zookeeper.data.retention",
    "local.zookeeper.config.baseline",
)

MODULE = MonitorModule("zookeeper", "ZooKeeper 中间件", ZOOKEEPER_METRIC_IDS)

__all__ = ["ZOOKEEPER_METRIC_IDS", "MODULE"]
