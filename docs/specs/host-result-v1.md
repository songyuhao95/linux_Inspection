# host-result-v1 数据契约（版本化 JSON 唯一事实源）

- 文档 ID：host-result-v1
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案

## 1. 设计原则（用户已确认）

1. **版本化 JSON 是唯一事实源**：一次采集 → 一次规范化 → 原子写入 JSON；终端/Excel/HTML 报表只消费 JSON，不二次采集、不修改事实。
2. **执行状态与业务状态分离**：`execution_status`（SUCCESS/PARTIAL/ERROR）描述"巡检动作是否成功执行"；`status`（OK/WARN/CRIT/UNKNOWN）描述"业务结论"。技术失败不得伪装成业务 CRIT。
3. **阈值可追溯**：每个业务状态必须能回溯到阈值层（文档基线 / 外部配置）与来源锚点；无规则或冲突 → `UNKNOWN`。
4. **脱敏**：JSON 中不出现凭据与明文敏感信息；IP/路径按配置边界处理。

## 2. 顶层结构

```json
{
  "schema": "host-result-v1",
  "schema_version": 1,
  "run_id": "run-20260814-001",
  "inspection_id": "insp-<yyyyMMddHHmmss>-<host>",
  "host": {
    "name": "<hostname>",
    "ip": "<IP>",
    "inventory_source": "<inventory 路径或 local>",
    "product_profiles": ["linux-common-p0-v1"]
  },
  "collected_at": "2026-08-15T10:30:00+08:00",
  "duration_sec": 12.4,
  "execution_status": "SUCCESS",
  "execution_summary": {
    "total_metrics": 10,
    "ok": 7,
    "warn": 1,
    "crit": 0,
    "unknown": 2,
    "executed": 10,
    "failed": 0
  },
  "metrics": [ { "metric": { ... } } ],
  "meta": {
    "control_endpoint": "Linux/WSL Python3",
    "gather_facts": false,
    "serial": 1,
    "become_scope": "minimal",
    "generator": "inspect.sh",
    "generator_version": "0.1.0-draft"
  }
}
```

### 2.1 execution_status 取值

| 值 | 含义 |
| --- | --- |
| SUCCESS | 所有指标动作执行完成，无技术失败 |
| PARTIAL | 部分指标动作失败（如某指标权限不足/超时）或部分主机失败；失败的指标以 error 记录并保持业务 `UNKNOWN` |
| ERROR | 整体执行失败（连接失败、inventory 解析失败、控制端故障）；此时不产生业务结论 |

### 2.2 业务 status 取值

| 值 | 含义 | 映射来源 |
| --- | --- | --- |
| OK | 正常 | 手册"正常标准"满足 |
| WARN | 关注 | 手册"关注"级异常 |
| CRIT | 告警/故障 | 手册"告警"与"故障"级（meta.priority: alert/fault） |
| UNKNOWN | 无规则/规则冲突/权限能力不足/数据缺失 | 阈值分层"无规则/冲突"层 |

## 3. metric 对象结构

```json
{
  "metric_id": "local.cpu.utilization",
  "name": "CPU 使用率",
  "scope": "local-common-p0-v1",
  "status": "WARN",
  "raw_value": "82.5",
  "normalized_value": 82.5,
  "unit": "%",
  "threshold": {
    "layer": "document-baseline",
    "rule_id": "linux-common-p0-v1.cpu.utilization.warn",
    "value": ">80",
    "source_anchor": "巡检手册/安徽农金Elasticsearch运维巡检手册v1.0.docx §三(二)P0/表T5R3/指纹bb8ff97e"
  },
  "evidence": {
    "command": "top -bn1 | head -20",
    "output_summary": "Cpu(s): 82.5% us, 10.2% sy, 7.3% id",
    "raw_ref": "run/raw/<insp>/local.cpu.utilization.out",
    "sampled_at": "2026-08-15T10:30:02+08:00"
  },
  "error": null,
  "provenance": {
    "config_sources": ["inventory:group_vars/all/p0_thresholds.yml (未使用)"],
    "doc_sources": ["巡检手册 v1.0 表T5R3"],
    "notes": "load_1m 无等级定义，未参与本次判定"
  }
}
```

### 3.1 字段语义

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| metric_id | 是 | 与 local-metrics-requirements.md 指标 ID 一致 |
| name | 是 | 指标中文名 |
| scope | 是 | 指标所属切片/版本（如 local-common-p0-v1） |
| status | 是 | OK/WARN/CRIT/UNKNOWN |
| raw_value | 是 | 采集原始值（字符串化，保留原文格式） |
| normalized_value | 否 | 规范化数值（统一单位、可比较）；无法规范化时 null |
| unit | 是 | 单位 |
| threshold | 是 | 阈值层 + 规则 ID + 判定值 + 来源锚点；UNKNOWN 时 value 可为 null 并注明原因（missing/conflict） |
| evidence | 是 | 命令、输出摘要、原始输出引用、采样时间；文件系统指标可选 `details` 数组，逐挂载点保存 `filesystem`、`mount`、`used_percent` 和可选 `status`；新事实源写入挂载点级状态，旧事实源缺少该字段时展示层回退到指标整体状态 |
| error | 否 | 技术错误（error_code + message）；仅执行失败时非空 |
| provenance | 是 | 配置来源、文档来源、解释性备注（含冲突/缺失说明） |

### 3.2 error 结构（技术失败，与业务 status 无关）

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "cannot read /opt/redis/logs (permission denied)",
    "metric_status": "UNKNOWN"
  }
}
```

error code 枚举（首版）：`CONNECTION_FAILED`、`TIMEOUT`、`PERMISSION_DENIED`、`COMMAND_NOT_FOUND`、`PARSE_FAILED`、`DATA_MISSING`、`PROBE_FAILED`、`UNSUPPORTED_PROFILE`。业务 `status` 在 error 存在时一律为 `UNKNOWN`。

## 4. 状态判定流程（不可变顺序）

```
1. 采集动作执行失败？ → status=UNKNOWN, error=<code>, execution_status=PARTIAL/ERROR（不参与业务判定）
2. 有外部配置阈值？ → 按外部配置判定（provenance 记录配置来源）
3. 无外部配置 → 按文档基线（linux-common-p0-v1）判定
4. 文档基线无规则或文档冲突 unresolved？ → status=UNKNOWN（threshold.notes 注明 missing/conflict）
5. 其余 → 按文档基线判定
```

禁止任何未锚定的阈值发明；`UNKNOWN` 是合法输出，不是失败。

## 5. 原子写与文件约定

- 每次巡检（每个主机）一个结果文件：`<输出目录>/hosts/<host>-<insp-id>.json`，写入流程：写临时文件 → fsync → 原子 rename。
- 汇总索引（可选）：`<输出目录>/inspection-<insp-id>-index.json`，引用各主机文件 sha256。
- 报表（stdout/Excel/HTML）只读上述 JSON；事实源一旦写出，报表阶段不得回写。
- 事实源文件命名/目录属配置边界，本契约只约束 schema 与语义。

## 6. 版本策略

- `schema_version` 只增不改语义；新增字段向后兼容（旧消费者忽略新字段）。
- 指标 ID 与阈值规则 ID 均带版本（`linux-common-p0-v1`）；规则变更升版本号，不覆盖历史事实。
- 本契约 v1 固定字段；中间件 profile 指标复用同一 metric 对象结构，不改 schema。

## 7. 完整示例（含 UNKNOWN 与 PARTIAL）

```json
{
  "schema": "host-result-v1",
  "schema_version": 1,
  "run_id": "run-20260814-001",
  "inspection_id": "insp-20260815103000-node-01",
  "host": { "name": "node-01", "ip": "<IP>", "inventory_source": "local" },
  "collected_at": "2026-08-15T10:30:00+08:00",
  "duration_sec": 12.4,
  "execution_status": "PARTIAL",
  "execution_summary": { "total_metrics": 10, "ok": 7, "warn": 1, "crit": 0, "unknown": 2, "executed": 10, "failed": 0 },
  "metrics": [
    {
      "metric_id": "local.filesystem.used_percent",
      "name": "磁盘使用率",
      "scope": "local-common-p0-v1",
      "status": "OK",
      "raw_value": "62",
      "normalized_value": 62.0,
      "unit": "%",
      "threshold": {
        "layer": "document-baseline",
        "rule_id": "linux-common-p0-v1.filesystem.used_percent.ok",
        "value": "<75",
        "source_anchor": "巡检手册/安徽农金Mysql运维巡检手册v1.0.docx §P0/表T5R9/指纹67ae309b"
      },
      "evidence": {
        "command": "df -hT",
        "output_summary": "/dev/mapper/vg-data 62%（/）；/dev/mapper/vg-log 81%（/var/log）",
        "raw_ref": "raw/local.filesystem.used_percent.out",
        "sampled_at": "2026-08-15T10:30:02+08:00",
        "details": [
          { "filesystem": "/dev/mapper/vg-data", "mount": "/", "used_percent": 62, "status": "OK" },
          { "filesystem": "/dev/mapper/vg-log", "mount": "/var/log", "used_percent": 81, "status": "WARN" }
        ]
      },
      "error": null,
      "provenance": { "config_sources": [], "doc_sources": ["Mysql 巡检手册 v1.0 表T5R9"] }
    },
    {
      "metric_id": "local.swap.used_percent",
      "name": "Swap 使用率",
      "scope": "local-common-p0-v1",
      "status": "UNKNOWN",
      "raw_value": "12.5",
      "normalized_value": 12.5,
      "unit": "%",
      "threshold": {
        "layer": "unresolved-document-conflict",
        "rule_id": null,
        "value": null,
        "source_anchor": "巡检手册 9 份 P0 内存行（见 docs/reviews/docx-source-conflicts.md C3）"
      },
      "evidence": { "command": "free -m", "output_summary": "Swap: 8191 1024 7167", "sampled_at": "2026-08-15T10:30:03+08:00" },
      "error": null,
      "provenance": {
        "config_sources": [],
        "doc_sources": ["ES/Kafka/Mysql/Nacos/Rabbitmq/Rocketmq/Tomcat 巡检手册"],
        "notes": "文档冲突 C3 unresolved：swap>0 的告警判据在 9 份手册间不一致，默认 UNKNOWN，外部配置可覆盖"
      }
    },
    {
      "metric_id": "local.logs.key_evidence",
      "name": "关键日志证据",
      "scope": "local-common-p0-v1",
      "status": "UNKNOWN",
      "raw_value": null,
      "normalized_value": null,
      "unit": "count",
      "threshold": { "layer": null, "rule_id": null, "value": null, "source_anchor": null },
      "evidence": { "command": "tail -300 /opt/redis/logs/redis.log", "output_summary": null, "sampled_at": null },
      "error": { "code": "PERMISSION_DENIED", "message": "cannot read /opt/redis/logs/redis.log (permission denied)", "metric_status": "UNKNOWN" },
      "provenance": { "config_sources": [], "doc_sources": ["Redis 巡检手册 v1.0 表T5R11"], "notes": "权限不足，指标 UNKNOWN，继续其余指标与主机" }
    }
  ],
  "meta": { "control_endpoint": "Linux/WSL Python3", "gather_facts": false, "serial": 1, "become_scope": "minimal", "generator": "inspect.sh", "generator_version": "0.1.0-draft" }
}
```

## 8. 与报表的关系

- stdout/Excel/HTML 按 `execution_status` 与 `status` 两个维度汇总：业务状态只描述业务；`execution_status != SUCCESS` 时报表必须展示技术失败计数（Errors-Evidence），不得掩盖为业务正常。
- 状态颜色/排序约定见 docs/specs/reporting-roadmap.md。

> 说明：文件系统指标的 metric 级 `status`、`raw_value` 和 `normalized_value` 仍按所有挂载点中的最大使用率聚合，用于主机摘要和阈值判定；`evidence.details[].status` 仅表示对应挂载点自身状态，报表不得把整体状态复制到每个挂载点。
