"""tests/test_fact_source.py — T-104 事实源持久化层测试（合同 AC-2）。

覆盖（合同必需步骤 6 + mitigations）：
  - 原子写：同目录 tmp → flush → fsync → os.replace（tmp 命名被
    .gitignore 忽略，无残留）；
  - inspection_id 唯一：重跑同 id 不覆盖 → FactSourceError；
  - 写入失败 → FactSourceError(exit_code=10)（cli-contract §4）；
  - 损坏检测：JSON 解析失败 / schema 校验失败 → FactSourceError（先全量
    校验后落盘，校验失败不产生任何文件）；
  - TD §3 目录布局：<out_dir>/<inspection_id>/hosts/<host>.json +
    inspection-<inspection_id>-index.json（每主机 sha256/execution_status/
    error 明细）；
  - 与 tests/fixtures/json/ 夹具联动（host-result-valid.json 往返读写）。

只读使用 tests/fixtures/json/；不连接、不执行命令。
"""

import json
from pathlib import Path

import pytest

from inspect import fact_source as fs
from inspect import normalize as n

FIXTURE_JSON = Path(__file__).parent / "fixtures" / "json"
RUN_ID = "run-20260814-001"


def valid_doc() -> dict:
    return json.loads(
        (FIXTURE_JSON / "host-result-valid.json").read_text(encoding="utf-8")
    )


def valid_docs(count: int = 2, inspection_id: str = "insp-20260814120000-node-fx01") -> list:
    """同一次巡检（共享 inspection_id，TD §3 布局）的多主机文档。"""
    docs = []
    for i in range(count):
        doc = valid_doc()
        doc["host"]["name"] = f"node-fx{i + 1:02d}"
        doc["inspection_id"] = inspection_id
        docs.append(doc)
    return docs


def index_path(tmp_path, inspection_id: str = "insp-20260814120000-node-fx01") -> Path:
    return tmp_path / inspection_id / f"inspection-{inspection_id}-index.json"


def error_doc() -> dict:
    """主机级 ERROR 文档（连接失败，无业务结论；AE §6）。"""
    return n.normalize_host_result(
        {
            "host": "node-err",
            "ip": "10.0.0.9",
            "probe": {},
            "probe_status": "failed",
            "host_error": {
                "code": n.ERROR_CONNECTION_FAILED,
                "message": "连接失败",
                "metric_status": "UNKNOWN",
            },
            "execution_status": "ERROR",
            "metrics": [],
            "summary": {"total": 0, "executed": 0, "failed": 0},
            "duration_sec": 1.0,
        },
        run_id=RUN_ID,
        inspection_id="insp-20260814120000-node-err",
        collected_at="2026-08-14T12:00:00+08:00",
    )


# --------------------------------------------------------------------------
# 1. 原子写（tmp → flush → fsync → os.replace）
# --------------------------------------------------------------------------


class TestAtomicWrite:
    def test_writes_content_and_sha256(self, tmp_path):
        data = {"schema": "probe", "version": 1}
        sha = fs.atomic_write_json(tmp_path / "x.json", data)
        raw = (tmp_path / "x.json").read_bytes()
        assert sha == fs.sha256_bytes(raw)
        assert json.loads(raw.decode("utf-8")) == data
        assert raw.endswith(b"\n")  # 尾随换行

    def test_refuses_overwrite(self, tmp_path):
        target = tmp_path / "x.json"
        fs.atomic_write_json(target, {"v": 1})
        with pytest.raises(fs.FactSourceError, match="重跑不覆盖"):
            fs.atomic_write_json(target, {"v": 2})
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}

    def test_overwrite_true_replaces(self, tmp_path):
        target = tmp_path / "x.json"
        sha1 = fs.atomic_write_json(target, {"v": 1})
        sha2 = fs.atomic_write_json(target, {"v": 2}, overwrite=True)
        assert sha1 != sha2
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}

    def test_no_tmp_residue(self, tmp_path):
        target = tmp_path / "x.json"
        fs.atomic_write_json(target, {"v": 1})
        residue = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
        assert residue == []

    def test_tmp_name_pattern_is_gitignored(self):
        # tmp 命名契约：文件名以 .tmp 结尾 → .gitignore `*.tmp` 覆盖
        # （崩溃残留不污染 git 状态）。git check-ignore 不要求文件存在。
        import subprocess

        repo_root = Path(__file__).parents[1]
        stale = (
            repo_root
            / "tests"
            / "fixtures"
            / "json"
            / ".x.json.tmp-1234-deadbeef.tmp"
        )
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(stale)],
            cwd=repo_root,
            capture_output=True,
        )
        assert proc.returncode == 0

    def test_write_error_exit_code_10(self, tmp_path):
        # 写入失败语义：cli-contract §4 → exit_code=10
        try:
            fs.atomic_write_json(tmp_path / "x.json", {"v": 1}, overwrite=False)
        except fs.FactSourceError:
            pytest.fail("首次写不应失败")
        with pytest.raises(fs.FactSourceError) as exc:
            fs.atomic_write_json(tmp_path / "x.json", {"v": 2})
        assert exc.value.exit_code == 10


# --------------------------------------------------------------------------
# 2. write_inspection（TD §3 目录布局 + 索引）
# --------------------------------------------------------------------------


class TestWriteInspection:
    def test_layout_and_returns(self, tmp_path):
        docs = valid_docs(2)
        out = fs.write_inspection(tmp_path, RUN_ID, "insp-20260814120000-node-fx01", docs)
        insp_dir = tmp_path / "insp-20260814120000-node-fx01"
        assert out["inspection_dir"] == str(insp_dir)
        assert out["index_file"] == str(
            insp_dir / "inspection-insp-20260814120000-node-fx01-index.json"
        )
        assert (insp_dir / "hosts" / "node-fx01.json").is_file()
        assert (insp_dir / "hosts" / "node-fx02.json").is_file()
        assert (insp_dir / "inspection-insp-20260814120000-node-fx01-index.json").is_file()

    def test_index_contents(self, tmp_path):
        docs = valid_docs(1)
        out = fs.write_inspection(tmp_path, RUN_ID, "insp-20260814120000-node-fx01", docs)
        index = json.loads(index_path(tmp_path).read_text(encoding="utf-8"))
        assert index["schema"] == "inspection-index-v1"
        assert index["version"] == 1
        assert index["run_id"] == RUN_ID
        assert index["inspection_id"] == "insp-20260814120000-node-fx01"
        assert isinstance(index["generated_at"], str) and index["generated_at"]
        assert len(index["hosts"]) == 1
        entry = index["hosts"][0]
        assert entry["host"] == "node-fx01"
        assert entry["file"] == out["entries"][0]["file"]
        assert entry["execution_status"] == "SUCCESS"
        assert entry["error"] is None
        host_raw = (
            tmp_path / "insp-20260814120000-node-fx01" / "hosts" / "node-fx01.json"
        ).read_bytes()
        assert entry["sha256"] == fs.sha256_bytes(host_raw)
        assert entry["sha256"] == out["entries"][0]["sha256"]

    def test_error_host_index_entry_carries_host_error(self, tmp_path):
        doc = error_doc()
        err = {
            "code": n.ERROR_CONNECTION_FAILED,
            "message": "连接失败",
            "metric_status": "UNKNOWN",
        }
        fs.write_inspection(
            tmp_path,
            RUN_ID,
            "insp-20260814120000-node-err",
            [doc],
            host_errors={"node-err": err},
        )
        index = fs.read_inspection_index(index_path(tmp_path, "insp-20260814120000-node-err"))
        entry = index["hosts"][0]
        assert entry["host"] == "node-err"
        assert entry["execution_status"] == "ERROR"
        assert entry["error"] == err
        assert (tmp_path / "insp-20260814120000-node-err" / "hosts" / "node-err.json").is_file()

    def test_rerun_same_inspection_id_refused(self, tmp_path):
        docs = valid_docs(1)
        insp_id = "insp-20260814120000-node-fx01"
        fs.write_inspection(tmp_path, RUN_ID, insp_id, docs)
        with pytest.raises(fs.FactSourceError, match="重跑不覆盖"):
            fs.write_inspection(tmp_path, RUN_ID, insp_id, docs)

    def test_validation_failure_creates_no_files(self, tmp_path):
        docs = valid_docs(1)
        docs[0]["metrics"][0]["status"] = "FATAL"
        with pytest.raises(fs.FactSourceError):
            fs.write_inspection(tmp_path, RUN_ID, "insp-20260814120000-node-fx01", docs)
        assert not (tmp_path / "insp-20260814120000-node-fx01").exists()

    def test_out_dir_is_file_raises_exit_10(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        docs = valid_docs(1)
        with pytest.raises(fs.FactSourceError) as exc:
            fs.write_inspection(blocker, RUN_ID, "insp-20260814120000-node-fx01", docs)
        assert exc.value.exit_code == 10

    def test_write_host_result_invalid_doc_raises(self, tmp_path):
        doc = valid_doc()
        doc["execution_status"] = "BOGUS"
        with pytest.raises(fs.FactSourceError):
            fs.write_host_result(tmp_path, doc)


# --------------------------------------------------------------------------
# 3. 读取与损坏检测（parse + schema 双保险）
# --------------------------------------------------------------------------


class TestRead:
    def test_roundtrip_valid_fixture(self):
        doc = fs.read_host_result(FIXTURE_JSON / "host-result-valid.json")
        assert doc == valid_doc()

    def test_roundtrip_after_write(self, tmp_path):
        doc = valid_doc()
        info = fs.write_host_result(tmp_path, doc)
        read_back = fs.read_host_result(info["file"])
        assert read_back == doc

    def test_corrupt_json_raises(self):
        with pytest.raises(fs.FactSourceError, match="JSON 解析失败"):
            fs.read_host_result(FIXTURE_JSON / "host-result-corrupt.json")

    def test_schema_invalid_raises(self, tmp_path):
        doc = valid_doc()
        doc["execution_status"] = "BOGUS"
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(fs.FactSourceError, match="schema 校验失败"):
            fs.read_host_result(bad)

    def test_validate_false_skips_schema(self, tmp_path):
        doc = valid_doc()
        doc["execution_status"] = "BOGUS"
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        assert fs.read_host_result(bad, validate=False)["execution_status"] == "BOGUS"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(fs.FactSourceError, match="读取失败"):
            fs.read_host_result(tmp_path / "nope.json")

    def test_read_inspection_index_roundtrip(self, tmp_path):
        fs.write_inspection(tmp_path, RUN_ID, "insp-20260814120000-node-fx01", valid_docs(1))
        index = fs.read_inspection_index(index_path(tmp_path))
        assert index["schema"] == "inspection-index-v1"
        assert index["hosts"][0]["host"] == "node-fx01"

    def test_read_inspection_index_corrupt(self, tmp_path):
        bad = tmp_path / "index.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(fs.FactSourceError, match="汇总索引读取失败"):
            fs.read_inspection_index(bad)

    def test_read_inspection_index_wrong_schema(self, tmp_path):
        bad = tmp_path / "index.json"
        bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
        with pytest.raises(fs.FactSourceError, match="schema 不符"):
            fs.read_inspection_index(bad)
