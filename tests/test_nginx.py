"""Nginx 中间件监控模块测试（nginx-p0-v1）。

覆盖：
  - 模块注册：nginx 进入默认注册表，middleware_module_ids() 只列中间件；
  - 指标定义：8 个 Nginx 指标、来源锚点、超时约定；
  - 进程发现选择（select_nginx_metrics）：运行中保留全部 / 未运行白名单外
    跳过 / 白名单内仅保留 process.present（CRIT 未运行）；
  - 解析器与判定（normalize）：config.valid / port.listening / error_log /
    connections.status / access_log.status_codes / config.baseline /
    security.baseline；
  - local_runner fixture 全链路（nginx-a 运行中 / nginx-absent 未运行）：
    事实源 schema、product_profiles、白名单 CRIT；
  - 渲染集成：HTML 中间件维度（local.nginx.* → nginx）、Excel nginx Sheet。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from inspect import ansible_runner as ar
from inspect import config as config_mod
from inspect import local_runner
from inspect import metrics as metrics_mod
from inspect import normalize as n
from inspect.modules import default_registry, middleware_module_ids

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "raw"
RUN_ID = "run-20260819-nginx"
COLLECTED = "2026-08-19T10:00:00+08:00"

NGINX_IDS = (
    "local.nginx.process.present",
    "local.nginx.config.valid",
    "local.nginx.port.listening",
    "local.nginx.error_log.key_evidence",
    "local.nginx.connections.status",
    "local.nginx.access_log.status_codes",
    "local.nginx.config.baseline",
    "local.nginx.security.baseline",
)

NGINX_PROFILE = config_mod.load_nginx_config()


def _raw(host: str, metric_id: str) -> str:
    return (FIXTURES / host / f"{metric_id}.out").read_text(encoding="utf-8")


def _host(name: str, ip: str):
    return SimpleNamespace(name=name, ip=ip)


def _selection(hosts):
    return SimpleNamespace(
        kind="local",
        inventory_file=str(ROOT / ".runtime" / "nginx-test.ini"),
        hosts=hosts,
        limit=None,
    )


def _nginx_specs():
    return ar.build_metric_command_specs(
        module_ids=("linux_basic", "nginx"), profile=NGINX_PROFILE
    )


def _metric_result(
    metric_id: str, stdout: str = "", *, rc: int = 0, stderr: str = "", error=None
) -> dict:
    return {"metric_id": metric_id, "rc": rc, "stdout": stdout, "stderr": stderr, "error": error}


def _host_result(host: str, metrics: list, ip: str = "192.168.0.101") -> dict:
    return {
        "host": host,
        "ip": ip,
        "probe": {},
        "probe_status": "ok",
        "host_error": None,
        "execution_status": "SUCCESS",
        "metrics": list(metrics),
        "summary": {"total": len(metrics), "executed": len(metrics), "failed": 0},
        "duration_sec": 1.0,
    }


def _normalize(run_result):
    resolved = config_mod.build_resolved_thresholds()
    return n.normalize_run_results(
        run_result,
        run_id=RUN_ID,
        inspection_id="insp-20260819100000-nginx",
        collected_at=COLLECTED,
        profile=None,
        product_profiles=[],
        resolved_thresholds=resolved,
        inventory_source="local",
        meta=None,
    )


# --------------------------------------------------------------------------
# 1. 模块注册
# --------------------------------------------------------------------------


class TestModuleRegistration:
    def test_nginx_module_registered(self):
        registry = default_registry()
        module = registry.get("nginx")
        assert module is not None
        assert module.display_name == "Nginx 中间件"
        assert module.metric_ids == NGINX_IDS
        assert middleware_module_ids() == ("nginx",)

    def test_nginx_metrics_in_catalog(self):
        for mid in NGINX_IDS:
            m = metrics_mod.get_metric(mid)
            assert m is not None, mid
            assert m["timeout_sec"] in (10, 15)
            assert m["parser"]
            assert "巡检手册" in m["source_anchor"]
            assert any(rid.startswith("nginx-p0-v1:") for rid in m["threshold_rule_ids"])

    def test_nginx_thresholds_resolved(self):
        resolved = config_mod.build_resolved_thresholds()
        for mid in NGINX_IDS:
            entry = resolved[mid]
            assert entry["layer"] == config_mod.LAYER_DOCUMENT_BASELINE, mid
            assert entry["version"] == config_mod.NGINX_BASELINE_VERSION, mid

    def test_config_valid_command_uses_configured_error_log(self):
        specs = _nginx_specs()
        spec = next(s for s in specs if s.metric_id == "local.nginx.config.valid")
        assert "-e /opt/nginx/logs/error.log" in spec.command


# --------------------------------------------------------------------------
# 2. 进程发现选择（select_nginx_metrics）
# --------------------------------------------------------------------------


class TestProcessDiscoverySelection:
    def _base(self):
        return [_metric_result("local.cpu.utilization", "x")]

    def test_present_keeps_all_nginx_metrics(self):
        metrics = self._base() + [
            _metric_result("local.nginx.process.present", "123 nginx: master process"),
            _metric_result("local.nginx.config.valid", "ok"),
        ]
        out = ar.select_nginx_metrics(metrics, host_ip="1.1.1.1", nginx_whitelist=[])
        assert [m["metric_id"] for m in out] == [
            "local.cpu.utilization", "local.nginx.process.present", "local.nginx.config.valid",
        ]

    def test_absent_outside_whitelist_drops_nginx_metrics(self):
        metrics = self._base() + [
            _metric_result("local.nginx.process.present", ""),
            _metric_result("local.nginx.config.valid", "ok"),
        ]
        out = ar.select_nginx_metrics(metrics, host_ip="1.1.1.1", nginx_whitelist=[])
        assert [m["metric_id"] for m in out] == ["local.cpu.utilization"]

    def test_absent_inside_whitelist_keeps_only_process_metric(self):
        metrics = self._base() + [
            _metric_result("local.nginx.process.present", ""),
            _metric_result("local.nginx.config.valid", "ok"),
        ]
        out = ar.select_nginx_metrics(
            metrics, host_ip="1.1.1.1", nginx_whitelist=["1.1.1.1"]
        )
        assert [m["metric_id"] for m in out] == [
            "local.cpu.utilization", "local.nginx.process.present",
        ]

    def test_discovery_error_keeps_all_nginx_metrics_as_unknown(self):
        metrics = self._base() + [
            _metric_result(
                "local.nginx.process.present", "",
                error={"code": ar.ERROR_PERMISSION_DENIED, "message": "denied"},
            ),
            _metric_result("local.nginx.config.valid", "ok"),
        ]
        out = ar.select_nginx_metrics(metrics, host_ip="1.1.1.1", nginx_whitelist=[])
        assert [m["metric_id"] for m in out] == [
            "local.cpu.utilization", "local.nginx.process.present", "local.nginx.config.valid",
        ]


# --------------------------------------------------------------------------
# 3. 解析器与判定
# --------------------------------------------------------------------------


class TestParsersAndJudgment:
    def test_config_valid_ok(self):
        parsed = n.parse_nginx_config_valid(
            "nginx: the configuration file /opt/nginx/conf/nginx.conf syntax is ok\n"
            "nginx: configuration file /opt/nginx/conf/nginx.conf test is successful\n"
        )
        assert parsed["valid"] is True

    def test_config_valid_invalid_crit(self):
        parsed = n.parse_nginx_config_valid(
            "nginx: [emerg] unknown directive \"foo\" in /opt/nginx/conf/nginx.conf:1\n"
        )
        assert parsed["valid"] is False

    def test_config_valid_success_written_to_stderr_is_ok(self):
        """nginx -t 的成功文本通常在 stderr，不能被当成配置失败。"""
        hr = _host_result(
            "nginx-a",
            [_metric_result(
                "local.nginx.config.valid",
                stderr=(
                    "nginx: the configuration file /opt/nginx/conf/nginx.conf syntax is ok\n"
                    "nginx: configuration file /opt/nginx/conf/nginx.conf test is successful\n"
                ),
            )],
        )
        doc = n.normalize_host_result(
            hr, run_id=RUN_ID, collected_at=COLLECTED,
            resolved_thresholds=config_mod.build_resolved_thresholds(),
        )
        metric = doc["metrics"][0]
        assert metric["status"] == "OK"
        assert metric["raw_value"] == "valid"
        assert "syntax is ok" in metric["evidence"]["output_summary"]

    def test_port_listening_ok(self):
        parsed = n.parse_nginx_port_listening(
            "LISTEN 0 511 0.0.0.0:8010 0.0.0.0:* users:((\"nginx\",pid=1234,fd=10))\n"
            "HTTP/1.1 200 OK\n"
        )
        assert parsed["listening"] is True
        assert parsed["http_status"] == 200

    def test_port_not_listening_crit(self):
        parsed = n.parse_nginx_port_listening("")
        assert parsed["listening"] is False
        assert parsed["http_status"] is None

    def test_error_log_no_hits_ok(self):
        parsed = n.parse_nginx_error_log("/opt/nginx/logs/error.log\n")
        assert parsed["hit_count"] == 0

    def test_error_log_hits_warn(self):
        parsed = n.parse_nginx_error_log(
            "/opt/nginx/logs/error.log\n"
            "2026/08/19 10:00:00 [error] 1234#0: connect() failed (111: Connection refused)\n"
        )
        assert parsed["hit_count"] == 1

    def test_error_log_missing_file_unknown(self):
        with pytest.raises(n.ParseError):
            n.parse_nginx_error_log("")

    def test_connections_status_configured(self):
        parsed = n.parse_nginx_connections_status(
            "Active connections: 42\nserver accepts handled requests\n"
            " 900 900 910\nReading: 0 Writing: 1 Waiting: 41\n"
        )
        assert parsed["configured"] is True
        assert parsed["active"] == 42

    def test_connections_status_not_configured(self):
        parsed = n.parse_nginx_connections_status("404 Not Found\n")
        assert parsed["configured"] is False

    def test_access_log_status_codes(self):
        parsed = n.parse_nginx_access_log_status_codes(
            "/opt/nginx/logs/access.log\n"
            '10.0.0.5 - - [18/Aug/2026:10:00:01 +0800] "GET / HTTP/1.1" 200 1024 "-"\n'
            '10.0.0.6 - - [18/Aug/2026:10:00:02 +0800] "GET /api HTTP/1.1" 503 512 "-"\n'
            '10.0.0.7 - - [18/Aug/2026:10:00:03 +0800] "GET /x HTTP/1.1" 404 0 "-"\n'
        )
        assert parsed["five_xx"] == 1
        assert parsed["counts"] == {"2xx": 1, "4xx": 1, "5xx": 1}

    def test_access_log_missing_file_unknown(self):
        with pytest.raises(n.ParseError):
            n.parse_nginx_access_log_status_codes("")

    def test_config_baseline(self):
        parsed = n.parse_nginx_config_baseline(
            "/opt/nginx/conf/nginx.conf\nworker_processes auto;\n"
            "worker_connections 10000;\nkeepalive_timeout 65;\n"
        )
        assert {"worker_processes", "worker_connections", "keepalive_timeout"} <= set(
            parsed["directives"]
        )

    def test_security_baseline_ok(self):
        parsed = n.parse_nginx_security_baseline(
            "/opt/nginx/conf/nginx.conf\nserver_tokens off;\nautoindex off;\n"
        )
        assert parsed["server_tokens_off"] is True
        assert parsed["autoindex_off"] is True

    def test_judgments_via_normalize_one(self):
        def one(mid, stdout):
            hr = _host_result("nginx-a", [_metric_result(mid, stdout)])
            doc = n.normalize_host_result(
                hr, run_id=RUN_ID, collected_at=COLLECTED,
                resolved_thresholds=config_mod.build_resolved_thresholds(),
            )
            return doc["metrics"][0]

        assert one("local.nginx.config.valid", _raw("nginx-a", "local.nginx.config.valid"))["status"] == "OK"
        assert one("local.nginx.port.listening", _raw("nginx-a", "local.nginx.port.listening"))["status"] == "OK"
        assert one("local.nginx.error_log.key_evidence", _raw("nginx-a", "local.nginx.error_log.key_evidence"))["status"] == "OK"
        assert one("local.nginx.connections.status", _raw("nginx-a", "local.nginx.connections.status"))["status"] == "OK"
        assert one("local.nginx.access_log.status_codes", _raw("nginx-a", "local.nginx.access_log.status_codes"))["status"] == "WARN"
        assert one("local.nginx.config.baseline", _raw("nginx-a", "local.nginx.config.baseline"))["status"] == "OK"
        assert one("local.nginx.security.baseline", _raw("nginx-a", "local.nginx.security.baseline"))["status"] == "OK"
        assert one("local.nginx.process.present", "")["status"] == "CRIT"


# --------------------------------------------------------------------------
# 4. local_runner fixture 全链路（运行中 / 未运行 + 白名单）
# --------------------------------------------------------------------------


class TestFixturePipeline:
    def test_nginx_host_full_pipeline(self, tmp_path):
        run_result = local_runner.run_local(
            _selection([_host("nginx-a", "192.168.0.101")]),
            _nginx_specs(),
            fixture_dir=FIXTURES,
            runtime_dir=tmp_path / "runtime",
        )
        normalized = _normalize(run_result)
        doc = normalized["documents"][0]
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert doc["host"]["product_profiles"] == ["nginx"]
        assert set(NGINX_IDS).issubset(by_id)
        assert by_id["local.nginx.process.present"]["status"] == "OK"
        assert by_id["local.nginx.access_log.status_codes"]["status"] == "WARN"
        # nginx-a 夹具只有 nginx 输出，linux_basic 六项 DATA_MISSING → PARTIAL；
        # 8 个 nginx 指标本身全部执行成功且无 error。
        assert doc["execution_status"] == "PARTIAL"
        for mid in NGINX_IDS:
            assert by_id[mid]["error"] is None, mid
        n.validate_host_result(doc)

    def test_absent_outside_whitelist_skipped(self, tmp_path):
        run_result = local_runner.run_local(
            _selection([_host("nginx-absent", "192.168.0.99")]),
            _nginx_specs(),
            fixture_dir=FIXTURES,
            runtime_dir=tmp_path / "runtime",
            nginx_whitelist=[],
        )
        normalized = _normalize(run_result)
        doc = normalized["documents"][0]
        assert doc["host"].get("product_profiles") == []
        assert not any(
            m["metric_id"].startswith("local.nginx.") for m in doc["metrics"]
        )

    def test_absent_inside_whitelist_crit(self, tmp_path):
        run_result = local_runner.run_local(
            _selection([_host("nginx-absent", "192.168.0.99")]),
            _nginx_specs(),
            fixture_dir=FIXTURES,
            runtime_dir=tmp_path / "runtime",
            nginx_whitelist=["192.168.0.99"],
        )
        normalized = _normalize(run_result)
        doc = normalized["documents"][0]
        by_id = {m["metric_id"]: m for m in doc["metrics"]}
        assert doc["host"]["product_profiles"] == ["nginx"]
        assert by_id["local.nginx.process.present"]["status"] == "CRIT"
        assert by_id["local.nginx.process.present"]["raw_value"] == "absent"
        assert not any(
            m["metric_id"] != "local.nginx.process.present"
            and m["metric_id"].startswith("local.nginx.")
            for m in doc["metrics"]
        )
        n.validate_host_result(doc)


# --------------------------------------------------------------------------
# 5. 渲染集成（HTML 中间件维度 / Excel nginx Sheet）
# --------------------------------------------------------------------------


class TestRenderIntegration:
    def test_html_middleware_dimension_nginx(self):
        from inspect import render_html as rh

        metric = {
            "metric_id": "local.nginx.process.present",
            "name": "Nginx 进程存在性",
            "status": "OK",
            "raw_value": "present",
            "normalized_value": None,
            "unit": "布尔",
            "threshold": {"layer": "document-baseline", "rule_id": "nginx-p0-v1.nginx.process.present.ok",
                          "value": "进程存在", "source_anchor": "a"},
            "evidence": {"command": "pgrep -fa 'nginx'", "output_summary": "present",
                         "sampled_at": COLLECTED},
            "provenance": {"config_sources": [], "doc_sources": ["a"], "notes": None},
        }
        assert rh._middleware_values({"host": {}}, metric) == ["nginx"]

    def test_html_linux_basics_stay_linux(self):
        from inspect import render_html as rh

        metric = {"metric_id": "local.cpu.utilization", "name": "CPU", "status": "OK"}
        assert rh._middleware_values({"host": {}}, metric) == ["Linux 基础"]

    def test_excel_nginx_sheet_contains_nginx_metrics_only(self, monkeypatch, tmp_path):
        import sys

        class _Sheet:
            def __init__(self, name):
                self.name = name
                self.cells = {}

            def write(self, row, col, value, fmt=None):
                self.cells[(row, col)] = [value]

            def set_column(self, *args):
                pass

            def freeze_panes(self, *args):
                pass

        class StubXlsxwriter:
            def __init__(self):
                self.workbooks = []
                self.sheets = []

            def Workbook(self, path):
                wb = _Workbook()
                self.workbooks.append(wb)
                return wb

        class _Workbook:
            def __init__(self):
                self.sheets = []

            def add_worksheet(self, name):
                sh = _Sheet(name)
                self.sheets.append(sh)
                return sh

            def add_format(self, *args, **kwargs):
                return object()

            def close(self):
                self.closed = True

        stub = StubXlsxwriter()
        monkeypatch.setitem(sys.modules, "xlsxwriter", stub)

        run_result = local_runner.run_local(
            _selection([_host("nginx-a", "192.168.0.101")]),
            _nginx_specs(),
            fixture_dir=FIXTURES,
            runtime_dir=tmp_path / "runtime",
        )
        normalized = _normalize(run_result)
        docs = normalized["documents"]

        from inspect import render_xlsx as rx

        rx.render_xlsx(docs, tmp_path / "nginx.xlsx")
        wb = stub.workbooks[-1]
        assert [s.name for s in wb.sheets] == list(rx.SHEET_NAMES)
        nginx_sheet = wb.sheets[2]
        metric_ids = {
            nginx_sheet.cells[(row, col)][0]
            for (row, col) in nginx_sheet.cells
            if col == 2 and row >= 1
        }
        assert metric_ids == set(NGINX_IDS)
        local_sheet = wb.sheets[1]
        local_metric_ids = {
            local_sheet.cells[(row, col)][0]
            for (row, col) in local_sheet.cells
            if col == 2 and row >= 1
        }
        assert local_metric_ids
        assert not any(mid.startswith("local.nginx.") for mid in local_metric_ids)
