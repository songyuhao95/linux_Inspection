"""Built-in Nginx middleware monitor module (nginx-p0-v1).

This module owns the Nginx (Nginx+Keepalived environment) middleware
metrics transcribed from 《安徽农金Nginx、Keepalived运维巡检手册v1.0》.
The module is selected explicitly via the CLI (default collects all
middleware; ``--nginx`` narrows to Nginx only).  Process discovery is
``local.nginx.process.present``: hosts without a running Nginx process are
skipped (their Nginx metrics are dropped), except whitelisted hosts where a
missing process is reported as CRIT "未运行".
"""

from .registry import MonitorModule

NGINX_METRIC_IDS = (
    "local.nginx.process.present",
    "local.nginx.version",
    "local.nginx.config.valid",
    "local.nginx.port.listening",
    "local.nginx.error_log.key_evidence",
    "local.nginx.connections.status",
    "local.nginx.access_log.status_codes",
    "local.nginx.config.baseline",
    "local.nginx.security.baseline",
    "local.nginx.http.reachability",
    "local.nginx.stub_status.connections",
    "local.nginx.proxy.upstream.config",
    "local.nginx.fd.process.limits",
    "local.nginx.https.certificate",
)

MODULE = MonitorModule(
    module_id="nginx",
    display_name="Nginx 中间件",
    metric_ids=NGINX_METRIC_IDS,
)

__all__ = ["MODULE", "NGINX_METRIC_IDS"]
