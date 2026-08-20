"""Built-in Elasticsearch middleware monitor module.

The adapter follows the same process-first discovery and whitelist contract as
Nginx and Keepalived.  A host without a running Elasticsearch process is
skipped unless its address is listed in ``inspect.conf`` as
``elasticsearch_whitelist``.
"""

from .registry import MonitorModule

ELASTICSEARCH_METRIC_IDS = (
    "local.elasticsearch.process.present",
    "local.elasticsearch.version",
    "local.elasticsearch.cluster.health",
    "local.elasticsearch.nodes.online",
    "local.elasticsearch.nodes.cpu",
    "local.elasticsearch.nodes.memory",
    "local.elasticsearch.nodes.disk",
    "local.elasticsearch.disk.watermark",
    "local.elasticsearch.shards.unassigned",
    "local.elasticsearch.service.port",
    "local.elasticsearch.heap.gc",
    "local.elasticsearch.thread_pool.rejected",
    "local.elasticsearch.cluster.settings",
    "local.elasticsearch.discovery.config",
    "local.elasticsearch.indices.health",
    "local.elasticsearch.slowlog.key_evidence",
    "local.elasticsearch.security.accounts",
    "local.elasticsearch.certificate.validity",
    "local.elasticsearch.snapshot.repository",
    "local.elasticsearch.system.parameters",
)

MODULE = MonitorModule(
    module_id="elasticsearch",
    display_name="Elasticsearch 中间件",
    metric_ids=ELASTICSEARCH_METRIC_IDS,
)

__all__ = ["MODULE", "ELASTICSEARCH_METRIC_IDS"]
