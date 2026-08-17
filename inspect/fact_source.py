"""inspect/fact_source.py — host-result-v1 事实源持久化（T-104）。

职责（docs/specs/host-result-v1.md §5、technical-design.md §3 目录布局、
REQ-D-05/REQ-E-11，TD §4 fact_source 行）：
  - 原子写：同目录 tmp 文件 → flush → os.fsync → os.replace（Windows
    上 os.replace 对已存在目标原子替换；tmp 文件名以 .tmp 结尾，
    已被 .gitignore 忽略，即使异常残留也不会污染 git 状态）；
  - inspection_id 唯一：目录已存在且未显式 overwrite → 拒绝（重跑
    不覆盖，R1 持久化不可变性）；
  - 写入失败 → FactSourceError（exit_code=10，cli-contract §4 执行失败）；
  - 损坏检测：read_host_result 做 JSON 解析 + host-result-v1 schema
    语义校验（normalize.validate_host_result，合同 mitigation）双保险；
  - 目录布局（TD §3）：<out_dir>/<inspection_id>/hosts/<host>.json +
    inspection-<inspection_id>-index.json；索引含每主机文件 sha256、
    execution_status 与主机级 error 明细（schema 无主机级 error 字段，
    ERROR 主机明细由索引承载，见 T-104 报告 D1）；
  - 先全量校验后落盘：write_inspection 在任何文件写入前完成全部文档
    schema 校验，校验失败不产生任何文件。

模块边界（TD §4）：fact_source → normalize（单向，允许）；不渲染、
不执行采集；不导入 config/metrics/ansible_runner。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from inspect import normalize

# cli-contract §4：事实源写入失败按执行失败处理
EXIT_WRITE_ERROR = 10

INDEX_SCHEMA = "inspection-index-v1"
INDEX_VERSION = 1


class FactSourceError(Exception):
    """事实源写入/读取失败（写入失败 → 调用方映射退出码 10）。"""

    def __init__(self, message: str, *, exit_code: int = EXIT_WRITE_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


def sha256_bytes(data: bytes) -> str:
    """内容 sha256（索引记录/测试断言用）。"""
    return hashlib.sha256(data).hexdigest()


def _encode_json(data: Any) -> bytes:
    """文档 JSON 字节（UTF-8，ensure_ascii=False 保留中文，尾随换行）。"""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write_json(
    path: Path, data: Any, *, overwrite: bool = False
) -> str:
    """原子写 JSON：同目录 tmp → flush → fsync → os.replace。

    - 目标已存在且 overwrite=False → FactSourceError（重跑不覆盖）；
    - 任一步 OSError → FactSourceError（exit_code=10 语义）；
    - 返回写入内容的 sha256（十六进制，索引与测试断言用）。
    """
    target = Path(path)
    if target.exists() and not overwrite:
        raise FactSourceError(f"目标已存在，重跑不覆盖: {target}")
    content = _encode_json(data)
    # 文件名以 .tmp 结尾（.gitignore `*.tmp` 覆盖）：即使进程在写入中途
    # 崩溃留下残留，也不会污染 git 状态
    tmp = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        with open(tmp, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise FactSourceError(f"事实源写入失败: {target}（{exc}）") from exc
    return sha256_bytes(content)


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_host_result(
    out_dir: Path, doc: Dict[str, Any], *, overwrite: bool = False
) -> Dict[str, Any]:
    """单主机文档落盘：<out_dir>/<inspection_id>/hosts/<host>.json（TD §3）。

    写前校验（normalize.validate_host_result）；校验失败 → FactSourceError
    （exit_code=10，写入失败语义）。返回 {"file", "sha256", "host",
    "execution_status"}。
    """
    try:
        normalize.validate_host_result(doc)
    except ValueError as exc:
        raise FactSourceError(f"事实源文档校验失败: {exc}") from exc
    host_name = doc["host"]["name"]
    host_file = Path(out_dir) / doc["inspection_id"] / "hosts" / f"{host_name}.json"
    try:
        host_file.parent.mkdir(parents=True, exist_ok=True)
        sha = atomic_write_json(host_file, doc, overwrite=overwrite)
    except OSError as exc:
        raise FactSourceError(f"事实源目录创建失败: {host_file.parent}（{exc}）") from exc
    return {
        "host": host_name,
        "file": str(host_file),
        "sha256": sha,
        "execution_status": doc["execution_status"],
    }


def write_inspection(
    out_dir: Path,
    run_id: str,
    inspection_id: str,
    docs: Sequence[Dict[str, Any]],
    host_errors: Optional[Mapping[str, Optional[Dict[str, Any]]]] = None,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """整次巡检落盘（TD §3 目录布局 + 汇总索引）。

    - inspection 目录已存在且未显式 overwrite → FactSourceError（inspection_id
      唯一，重跑不覆盖，R1 持久化）；
    - 全部文档先校验后落盘（校验失败 → 不产生任何文件）；
    - 每主机文件 sha256 与 execution_status 记入索引；主机级 error
      （ERROR 主机明细）由 host_errors 记入索引（schema 无主机级 error
      字段，见报告 D1）；
    - 返回 {"inspection_dir", "index_file", "entries"}（entries 与 docs 同序）。
    """
    out_dir = Path(out_dir)
    if not run_id or not isinstance(run_id, str):
        raise FactSourceError("run_id 必须为非空字符串")
    if not inspection_id or not isinstance(inspection_id, str):
        raise FactSourceError("inspection_id 必须为非空字符串")
    insp_dir = out_dir / inspection_id
    if insp_dir.exists() and not overwrite:
        raise FactSourceError(
            f"inspection 已存在，inspection_id 唯一（重跑不覆盖）: {insp_dir}"
        )

    # 先全量校验后落盘：任何文档校验失败 → 不产生任何文件；且同一次巡检
    # 全部文档必须共享本次 inspection_id（TD §3 布局：<inspection_id>/hosts/）
    for doc in docs:
        try:
            normalize.validate_host_result(doc)
        except ValueError as exc:
            raise FactSourceError(f"事实源文档校验失败: {exc}") from exc
        if doc["inspection_id"] != inspection_id:
            raise FactSourceError(
                f"文档 inspection_id 与本次巡检不一致: {doc['host']['name']} "
                f"→ {doc['inspection_id']!r} ≠ {inspection_id!r}"
            )

    host_errors = host_errors or {}
    entries: List[Dict[str, Any]] = []
    for doc in docs:
        info = write_host_result(out_dir, doc, overwrite=overwrite)
        info["error"] = host_errors.get(doc["host"]["name"])
        entries.append(info)

    index = {
        "schema": INDEX_SCHEMA,
        "version": INDEX_VERSION,
        "run_id": run_id,
        "inspection_id": inspection_id,
        "generated_at": _iso_now(),
        "hosts": entries,
    }
    index_file = insp_dir / f"inspection-{inspection_id}-index.json"
    try:
        atomic_write_json(index_file, index, overwrite=overwrite)
    except OSError as exc:
        raise FactSourceError(f"汇总索引写入失败: {index_file}（{exc}）") from exc
    return {
        "inspection_dir": str(insp_dir),
        "index_file": str(index_file),
        "entries": entries,
    }


def read_host_result(path: Path, *, validate: bool = True) -> Dict[str, Any]:
    """读取并校验 host-result-v1 文档（损坏检测：parse + schema 双保险）。

    - 文件不存在/不可读/非法 JSON → FactSourceError（exit_code=10）；
    - validate=True：normalize.validate_host_result 语义校验失败 →
      FactSourceError（损坏文件检测，合同 mitigation "parse+schema"）。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FactSourceError(f"事实源读取失败: {p}（{exc}）") from exc
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise FactSourceError(f"事实源损坏（JSON 解析失败）: {p}（{exc}）") from exc
    if validate:
        try:
            normalize.validate_host_result(doc, source=str(p))
        except ValueError as exc:
            raise FactSourceError(f"事实源损坏（schema 校验失败）: {p}（{exc}）") from exc
    return doc


def read_inspection_index(path: Path) -> Dict[str, Any]:
    """读取汇总索引（损坏/结构不符 → FactSourceError）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        index = json.loads(text)
    except (OSError, UnicodeError, ValueError) as exc:
        raise FactSourceError(f"汇总索引读取失败: {p}（{exc}）") from exc
    if not isinstance(index, dict) or index.get("schema") != INDEX_SCHEMA:
        raise FactSourceError(f"汇总索引损坏（schema 不符）: {p}")
    return index


__all__ = [
    "EXIT_WRITE_ERROR",
    "FactSourceError",
    "atomic_write_json",
    "read_host_result",
    "read_inspection_index",
    "sha256_bytes",
    "write_host_result",
    "write_inspection",
]
