# G2 技术设计（local 垂直切片）

- 文档 ID：technical-design
- 所属合同：contract-T-002-v1（run-20260814-001 / T-002 / phase=plan）
- 版本：v1（2026-08-15）
- 状态：G2 方案文档（待 G2 批准；设计决策引用 G1 已批准文档，未决项显式标注）
- 需求映射：docs/specs/requirements-acceptance-matrix.md（REQ-* ID）
- 说明：本文件是**设计**，不含实现代码；示例命令均来自 G1 文档数据源列，非新增。

## 1. 目标与范围

冻结 G2 待定项（目录布局、模块边界、probe 命令与解析器、阈值 override 语法、JSON Schema、Excel/HTML 库与模板、兼容矩阵、调试路径、回滚），使 T-101..T-108 可在互不重叠的写范围内独立实现、测试与合并。范围=local 垂直切片：10 个共同 P0 指标（MR §5）经 Ansible 采集→normalize→原子写 host-result-v1 JSON（HR）→stdout/Excel/离线单文件 HTML 三类报表（RR）。

## 2. 总体架构与数据流

```
inspect.sh（bash 入口，无业务逻辑：exec python3 -m inspect.cli "$@"）
  └─ inspect/cli.py         CLI 解析（argparse）· 主机选择 · 退出码映射 · 编排
       ├─ inspect/config.py      配置加载与阈值分层合并（文档基线 → 外部配置）
       ├─ inspect/inventory.py   -H 生成临时 inventory / -i 解析 / --limit / --all
       ├─ inspect/ansible_runner.py  生成 playbook → ansible-playbook 执行 → 结果回传
       │    ├─ inspect/probe.py      能力探测命令与解析（bash/pgrep/ss/free/df/...）
       │    └─ inspect/metrics.py    10 个 P0 指标定义（命令/超时/解析器/来源锚点）
       ├─ inspect/normalize.py  原始输出 → metric 对象（解析/脱敏/状态判定/provenance）
       ├─ inspect/fact_source.py    原子写 host-result-v1 JSON（唯一事实源）+ 汇总索引
       └─ 渲染层（只读 JSON，不二次采集）
            ├─ inspect/render_stdout.py
            ├─ inspect/render_xlsx.py
            └─ inspect/render_html.py（模板 inspect/templates/html-report-v1.html）
```

数据流单向：`采集 → normalize → 原子写 JSON → 报表`（RR §1）。`execution_status` 与业务 `status` 全程分离（HR §1.2），任何一层不得把技术失败伪装成业务 CRIT（AE §6）。

## 3. 目录布局

```
<仓库根>
├── inspect.sh                        # CLI 入口（bash 包装，仅定位 python3 与包路径）
├── inspect/                          # Python 实现包（控制端）
│   ├── __init__.py
│   ├── cli.py                        # 参数解析、主机选择、退出码映射、编排
│   ├── config.py                     # inspect.yml 加载、阈值分层合并、provenance 记录
│   ├── inventory.py                  # -H → 临时 inventory（.runtime/）；-i/--limit/--all 解析
│   ├── ansible_runner.py             # playbook 生成与执行、结果回传、fixture 模式注入点
│   ├── probe.py                      # 能力探测命令集合与解析（AE §3）
│   ├── metrics.py                    # 10 个 P0 指标定义表（命令/超时/解析器/单位/锚点/阈值规则 ID）
│   ├── normalize.py                  # 原始输出 → metric 对象（脱敏、解析、四状态判定）
│   ├── fact_source.py                # 原子写 host-result-v1 JSON + 汇总索引
│   ├── render_stdout.py              # stdout 终端渲染
│   ├── render_xlsx.py                # Excel 渲染（xlsxwriter）
│   ├── render_html.py                # 离线单文件 HTML 渲染（stdlib）
│   ├── schema/
│   │   ├── host-result-v1.schema.json          # 事实源 JSON Schema（机器可执行）
│   │   └── threshold-override-v1.schema.json   # 阈值 override 文件 Schema（机器可执行）
│   ├── templates/
│   │   └── html-report-v1.html       # 离线单文件 HTML 模板（RR §4 布局）
│   └── data/
│       └── thresholds/linux-common-p0-v1.yaml  # 文档基线阈值（转写 G1 MR §6，含来源锚点）
├── tests/
│   ├── test_cli.py / test_metrics.py / test_config.py / test_inventory.py
│   ├── test_ansible_runner.py / test_normalize.py / test_fact_source.py
│   ├── test_render_stdout.py / test_render_xlsx.py / test_render_html.py / test_e2e.py
│   └── fixtures/
│       ├── cli/ config/ inventory/ raw/ json/ stdout/ xlsx/ html/ e2e/   # 每任务独立夹具子目录
├── pyproject.toml                    # 包元数据与测试配置（pytest）
├── requirements.txt                  # 运行时依赖：xlsxwriter（选型见 §8）
├── requirements-dev.txt              # 开发依赖：pytest、jsonschema、openpyxl（仅校验）
├── docs/runbook.md                   # 本地调试与兼容矩阵执行手册（T-108 交付）
├── out/                              # 运行输出目录（默认；inspect.yml 可改；.gitignore）
└── .runtime/                         # 临时 inventory/playbook/raw 输出（运行期生成；.gitignore）
```

运行输出约定（HR §5）：每次巡检每主机一个事实源文件：

```
out/<inspection-id>/
├── hosts/<host>.json                  # 每主机 host-result-v1 JSON（原子写）
├── raw/<metric_id>.out                # 原始输出（本地保留，不进报表）
├── inspection-<inspection-id>-index.json   # 汇总索引（可选，引用各主机 sha256）
├── <inspection-id>.xlsx               # Excel（--excel PATH 可覆盖）
└── <inspection-id>.html               # 离线单文件 HTML（--html PATH 可覆盖）
```

输出目录为配置边界（HR §5"文件命名/目录属配置边界"），由 inspect.yml 的 `out_dir` 提供，默认 `out/`；不新增 CLI 选项（CC §2 选项表为冻结集）。

## 4. 模块边界与接口契约

依赖方向单向：`cli → config/inventory/ansible_runner/fact_source/renderers`；`ansible_runner → probe/metrics`；`normalize → config/metrics`；`fact_source → normalize`；渲染层只依赖 `config`（阈值展示）与事实源 JSON 读取。**禁止反向依赖与环**（结构审查项）。

| 模块 | 职责 | 输入 | 输出 | 禁止行为 |
| --- | --- | --- | --- | --- |
| inspect.sh | 定位 python3 与包路径并 exec | CLI 参数 | 进程 | 任何解析/采集逻辑 |
| cli.py | 参数解析、主机选择、退出码 0/2/10/20、编排、--list-metrics/--info | argv | 退出码 | 直接执行采集命令、连接主机 |
| config.py | inspect.yml/thresholds-override.yml 加载、分层合并（外部配置>文档基线>UNKNOWN）、provenance | 配置文件路径 | 合并后的阈值与 profile 上下文 | 发明阈值 |
| inventory.py | -H 生成临时 inventory、-i 解析、--limit/--all | 主机参数 | inventory 文件路径与主机列表 | 解析失败静默跳过（→10） |
| ansible_runner.py | playbook 生成（gather_facts:false、serial:1、raw/script+/bin/bash -lc）、执行、结果回传、fixture 注入 | inventory、指标命令集合 | 每主机每指标原始输出 + 能力矩阵 + execution 状态 | 非 allow-list 命令、become 滥用、重试 |
| probe.py | 能力探测命令与解析 | 主机 | 能力矩阵（命令可用性） | 探测之外的命令执行 |
| metrics.py | 10 个 P0 指标定义（数据源命令、超时、解析器名、单位、锚点、阈值规则 ID） | — | 指标注册表（供 --list-metrics/--info/采集/解析共用） | 定义之外的命令 |
| normalize.py | 原始输出→metric 对象：解析、脱敏、四状态判定、threshold/provenance | 原始输出 + 配置 | metric 对象 | 修改原始输出、把技术失败标为业务状态 |
| fact_source.py | 原子写（tmp→fsync→rename）、汇总索引 | metric 对象 | 事实源 JSON | 覆盖历史文件 |
| render_*.py | 只读 JSON → stdout/xlsx/html | 事实源 JSON | 报表 | 二次采集、访问网络/主机 |
| schema/*.json | JSON Schema 校验事实源与 override 文件 | — | Schema 文本 | 与 G1 契约不一致的字段 |

## 5. 能力探测与 10 个 P0 指标：probe 命令与解析器

### 5.1 能力探测（每主机执行一次，AE §3）

命令（`/bin/bash -lc` 包裹，超时 15s，输出逐行解析为能力矩阵）：

```
command -v bash; command -v pgrep; command -v ps; command -v ss; command -v free;
command -v df; command -v top; command -v systemctl; command -v tail; command -v grep; command -v nproc
```

解析规则：每行 `command -v X` 成功输出绝对路径→`X: available`；非零/无输出→`X: missing`。bash 不可用→该主机整体 `execution_status=ERROR`，不产生业务结论；其余命令缺失→相关指标 `UNKNOWN`（error=COMMAND_NOT_FOUND）并继续（AE §3）。

### 5.2 指标采集命令、超时与解析器

命令均来自 MR §5 各指标"数据源"列（文档锚点）；超时：指标命令 10s，日志类 15s（MR §5 / AE §7）；单主机总时长上限 300s。解析器在 normalize.py 内按指标注册，样例输出夹具在 tests/fixtures/raw/。

| metric_id | 采集命令（raw + /bin/bash -lc，来自 MR 数据源列） | 解析器与规范化 | 判定入口（阈值见 §6 基线文件） | UNKNOWN 条件（MR §5/DC） |
| --- | --- | --- | --- | --- |
| local.process.present | `pgrep -fa '<profile 进程模式>' \|\| ps -ef \| grep '[p]attern'`（pattern 来自 profile） | 行数≥1→present，0→absent；记录匹配行摘要（脱敏） | 存在→OK；缺失→CRIT（故障） | 无 profile 配置 |
| local.service.active | `systemctl is-active <unit>; systemctl show -p ActiveState,SubState <unit>`（unit 来自 profile，C8 配置边界） | 枚举 active/inactive/failed/unknown/not-found | active→OK；非 active→CRIT | unit 无配置（C8） |
| local.port.listening | `ss -tlnp` 按 profile 端口过滤 + 监听进程核对 | 端口列表 + 监听进程名（IP 脱敏为 `<IP>`） | 监听且进程匹配→OK；不监听→CRIT；模式外端口（如 Kafka 9092）→WARN 需确认（C7） | 端口/模式无配置（C13） |
| local.cpu.utilization | `top -bn1 \| head -20`；`ps -eo pid,comm,%cpu,%mem --sort=-%cpu \| head -10` | CPU 行 us/sy/id 数值；Top 进程行脱敏 | 长期<70% 且波动<80%→OK；持续>80%→WARN；>90% 且伴随业务证据→CRIT（C2 层级差异标注） | 采样失败；>90% 无业务证据采集能力→保持 WARN + provenance.notes 注明"CRIT 子判据需业务证据，首版未采集" |
| local.cpu.load_1m | `cat /proc/loadavg`；`nproc` | load_1m/5m/15m + 核数；持续性需两次采样间隔 ≥60s | ≤核数→OK；持续>核数→等级缺失→UNKNOWN（C5） | 核数不可得 |
| local.memory.available_percent | `free -m` | available/total×100 取整 | ≥20%→OK；<10%→CRIT；10–20%→缺失→UNKNOWN（C4） | 无法读取 |
| local.swap.used_percent | `free -m` Swap 行（或 /proc/meminfo SwapTotal/SwapFree） | used/total×100；total=0→未配置 | =0/未配置→OK；>0→判据冲突→UNKNOWN（C3） | — |
| local.filesystem.used_percent | `df -hT <profile 路径…>`（多目录取最大） | used/total×100，按文件系统取最大值 | <75%→OK；75–85%→WARN；>85%→CRIT；>95%→故障 CRIT（C1 建议线差异标注；C6 并入 CRIT） | 目录不可读 |
| local.filesystem.inode_used_percent | `df -i <profile 路径…>`（多目录取最大） | used/total×100 | <80%→OK；≥80%→缺失→UNKNOWN（C5） | 不可读 |
| local.logs.key_evidence | `tail -300 <profile 日志路径> \| egrep -i '<profile 关键词>'`（15s） | 命中行数 + 关键词分布 + 最近命中行摘要（脱敏） | 无新增不可解释 ERROR/FATAL→OK；命中按产品手册判定，冲突未解决→UNKNOWN（C10） | 日志不可读→UNKNOWN（非 OK） |

解析器通用规则（normalize.py）：解析失败→`error.code=PARSE_FAILED`、status=UNKNOWN、execution_status 保持采集层结果；原始输出摘要保留在 evidence.output_summary，原文只落 `.runtime/`（AE §4.5）。

## 6. 阈值 override 文件语法

### 6.1 阈值分层（G1 已确认，MR §3）

外部配置优先于文档基线；无规则或冲突→`UNKNOWN`；`provenance.config_sources` 记录配置来源。工具**不发明阈值**：文档基线文件 `inspect/data/thresholds/linux-common-p0-v1.yaml` 是 MR §6 汇总表的逐项转写（每条带 `source_anchor`），override 文件内容由现场/用户提供。

### 6.2 thresholds-override.yml（阈值覆盖，机器校验见 §7）

```yaml
schema: threshold-override-v1
version: 1
# scope 与 hosts 可选：限定生效范围；缺省对全部目标生效
scope: null
hosts: null
metrics:
  # 规则按数组顺序求值，首个匹配生效；数值比较作用于 normalized_value
  local.swap.used_percent:            # C3 unresolved 边界：现场基线可在此覆盖
    rules:
      - { status: WARN, op: ">", value: 0, note: "现场基线：启用 swap 监控（覆盖 C3）" }
  local.filesystem.inode_used_percent:  # C5 缺失边界覆盖示例（值由现场提供）
    rules:
      - { status: WARN, op: ">=", value: 80, note: "现场基线（覆盖 C5）" }
  local.cpu.load_1m:                    # C5 缺失边界覆盖示例（值由现场提供）
    rules:
      - { status: WARN, op: ">", value: 1.0, note: "持续超核数 1 倍（覆盖 C5，需现场确认）" }
```

语法约束：`status ∈ {OK, WARN, CRIT}`；判定表达式 `op+value`（op ∈ `> >= < <= == !=`）与 `range:[min,max]` 二选一（oneOf）；`note` 必填（回填 provenance.notes）。schema 校验失败→配置错误按执行失败处理（退出码 10，CC §4）。

### 6.3 inspect.yml（配置边界：产品 profile 与运行参数）

```yaml
schema: inspect-config-v1
version: 1
out_dir: out                       # 事实源与报表输出目录（HR §5 配置边界）
inventory: null                    # 可选的默认 inventory 路径（-i 优先级更高）
profiles:                          # 产品 profile：进程/unit/端口/路径/关键词均属配置边界
  elasticsearch:
    process_pattern: "org.elasticsearch.bootstrap.Elasticsearch"
    unit: elasticsearch
    ports: [9200, 9300]
    fs_paths: ["/opt/elasticsearch/data", "/opt/elasticsearch/logs"]
    log_paths: ["/opt/elasticsearch/logs/*.log"]
    log_keywords: ["ERROR", "master not discovered", "flood stage", "OutOfMemory"]
  # ... 其余产品由现场配置（C7/C8/C13 均以配置为准）
```

无 profile 配置→相关指标 `UNKNOWN`（MR §5 适用条件列），不静默跳过。

## 7. 机器可执行 JSON Schema

两份 Schema（draft-07）随包发布（inspect/schema/），实现阶段以 jsonschema 库（dev 依赖）校验。完整文本如下，实现时逐字落盘。

### 7.1 inspect/schema/host-result-v1.schema.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "host-result-v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "schema_version", "run_id", "inspection_id", "host", "collected_at", "duration_sec", "execution_status", "execution_summary", "metrics", "meta"],
  "properties": {
    "schema": { "const": "host-result-v1" },
    "schema_version": { "const": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "inspection_id": { "type": "string", "pattern": "^insp-[0-9]{14}-[A-Za-z0-9_.-]+$" },
    "host": {
      "type": "object", "additionalProperties": false,
      "required": ["name", "ip", "inventory_source"],
      "properties": {
        "name": { "type": "string", "minLength": 1 },
        "ip": { "type": "string", "minLength": 1 },
        "inventory_source": { "type": "string", "minLength": 1 },
        "product_profiles": { "type": "array", "items": { "type": "string" } }
      }
    },
    "collected_at": { "type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T" },
    "duration_sec": { "type": "number", "minimum": 0 },
    "execution_status": { "enum": ["SUCCESS", "PARTIAL", "ERROR"] },
    "execution_summary": {
      "type": "object", "additionalProperties": false,
      "required": ["total_metrics", "ok", "warn", "crit", "unknown", "executed", "failed"],
      "properties": {
        "total_metrics": { "type": "integer", "minimum": 0 },
        "ok": { "type": "integer", "minimum": 0 },
        "warn": { "type": "integer", "minimum": 0 },
        "crit": { "type": "integer", "minimum": 0 },
        "unknown": { "type": "integer", "minimum": 0 },
        "executed": { "type": "integer", "minimum": 0 },
        "failed": { "type": "integer", "minimum": 0 }
      }
    },
    "metrics": { "type": "array", "items": { "$ref": "#/definitions/metric" } },
    "meta": {
      "type": "object", "additionalProperties": false,
      "required": ["control_endpoint", "gather_facts", "serial", "become_scope", "generator", "generator_version"],
      "properties": {
        "control_endpoint": { "const": "Linux/WSL Python3" },
        "gather_facts": { "const": false },
        "serial": { "const": 1 },
        "become_scope": { "const": "minimal" },
        "generator": { "const": "inspect.sh" },
        "generator_version": { "type": "string", "minLength": 1 }
      }
    }
  },
  "definitions": {
    "metric": {
      "type": "object", "additionalProperties": false,
      "required": ["metric_id", "name", "scope", "status", "raw_value", "unit", "threshold", "evidence", "provenance"],
      "properties": {
        "metric_id": { "type": "string", "pattern": "^local\\." },
        "name": { "type": "string", "minLength": 1 },
        "scope": { "type": "string", "minLength": 1 },
        "status": { "enum": ["OK", "WARN", "CRIT", "UNKNOWN"] },
        "raw_value": { "type": ["string", "number", "boolean", "null"] },
        "normalized_value": { "type": ["number", "null"] },
        "unit": { "type": "string", "minLength": 1 },
        "threshold": { "$ref": "#/definitions/threshold" },
        "evidence": { "$ref": "#/definitions/evidence" },
        "error": { "anyOf": [{ "type": "null" }, { "$ref": "#/definitions/error" }] },
        "provenance": { "$ref": "#/definitions/provenance" }
      }
    },
    "threshold": {
      "type": "object", "additionalProperties": false,
      "required": ["layer", "rule_id", "value", "source_anchor"],
      "properties": {
        "layer": { "enum": ["document-baseline", "external-config", "unresolved-document-conflict", null] },
        "rule_id": { "type": ["string", "null"] },
        "value": { "type": ["string", "number", "null"] },
        "source_anchor": { "type": ["string", "null"] },
        "notes": { "type": ["string", "null"] }
      }
    },
    "evidence": {
      "type": "object", "additionalProperties": false,
      "required": ["command", "output_summary", "sampled_at"],
      "properties": {
        "command": { "type": "string" },
        "output_summary": { "type": ["string", "null"] },
        "raw_ref": { "type": ["string", "null"] },
        "sampled_at": { "type": ["string", "null"] }
      }
    },
    "error": {
      "type": "object", "additionalProperties": false,
      "required": ["code", "message", "metric_status"],
      "properties": {
        "code": { "enum": ["CONNECTION_FAILED", "TIMEOUT", "PERMISSION_DENIED", "COMMAND_NOT_FOUND", "PARSE_FAILED", "DATA_MISSING", "PROBE_FAILED", "UNSUPPORTED_PROFILE"] },
        "message": { "type": "string" },
        "metric_status": { "const": "UNKNOWN" }
      }
    },
    "provenance": {
      "type": "object", "additionalProperties": false,
      "required": ["config_sources", "doc_sources"],
      "properties": {
        "config_sources": { "type": "array", "items": { "type": "string" } },
        "doc_sources": { "type": "array", "items": { "type": "string" } },
        "notes": { "type": ["string", "null"] }
      }
    }
  }
}
```

### 7.2 inspect/schema/threshold-override-v1.schema.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "threshold-override-v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "version", "metrics"],
  "properties": {
    "schema": { "const": "threshold-override-v1" },
    "version": { "const": 1 },
    "scope": { "type": ["string", "null"] },
    "hosts": { "type": ["array", "null"], "items": { "type": "string" } },
    "metrics": {
      "type": "object",
      "propertyNames": { "pattern": "^local\\." },
      "additionalProperties": { "$ref": "#/definitions/metric_override" }
    }
  },
  "definitions": {
    "metric_override": {
      "type": "object", "additionalProperties": false,
      "required": ["rules"],
      "properties": {
        "rules": {
          "type": "array", "minItems": 1,
          "items": {
            "type": "object", "additionalProperties": false,
            "required": ["status"],
            "oneOf": [
              { "required": ["op", "value"] },
              { "required": ["range"] }
            ],
            "properties": {
              "status": { "enum": ["OK", "WARN", "CRIT"] },
              "op": { "enum": [">", ">=", "<", "<=", "==", "!="] },
              "value": { "type": "number" },
              "range": { "type": "array", "minItems": 2, "maxItems": 2, "items": { "type": "number" } },
              "note": { "type": "string", "minLength": 1 }
            }
          }
        }
      }
    }
  }
}
```

## 8. Excel/HTML 库与模板选型（离线单文件约束）

| 报表 | 选型 | 理由 | 失败处理 | 测试校验 |
| --- | --- | --- | --- | --- |
| Excel | **xlsxwriter**（运行时依赖，requirements.txt） | 纯 Python 无原生依赖、仅写模式（本产品只写不读）、支持多 Sheet/样式（三 Sheet 布局 RR §3）、离线 wheel 可分发型安装 | 未安装→明确报错"xlsxwriter 未安装，无法生成 Excel"退出码 10（不静默跳过）；具体版本 G0 预检后锁定，不承诺 | 生成文件 Sheet 名/单元格断言（dev 依赖 openpyxl 只读校验，或 zipfile+XML） |
| HTML | **零库**：stdlib `html` 转义 + 模板文件 `inspect/templates/html-report-v1.html`（string.Template 占位符渲染） | 离线单文件约束（RR §4）：CSS/JS 全内联、无外链 `<link>`/`<script src>`/fetch、无字体与网络请求；数据以 `<script type="application/json">` 内嵌，展示层零计算 | 模板缺失/占位符不全→渲染错误退出码 10 | 无外链文本断言 + 内嵌 JSON 与事实源一致性断言 |
| stdout | stdlib 格式化 | 无依赖 | — | 内容断言（RR §2） |

模板布局唯一来源=RR §4（左导航：run 摘要/主机列表/状态筛选；右滚动区：宏观卡片→主机详情逐指标卡片；打印友好）；四状态颜色/徽标=RR §5（OK #2E7D32 / WARN #F9A825 / CRIT #C62828 / UNKNOWN #757575；execution_status 徽标区分）。测试运行器 pytest（dev）；断言以 unittest 风格亦可，不做强制。

## 9. 兼容测试矩阵（Kylin V10 + 控制端 Linux/WSL）

本矩阵是**测试计划**，不是能力承诺；未验证项标"待 G0 预检/现网"（PB §9、AE §8）。T0=本地无目标主机（fixture/--local），T1=真实远程。

| # | 控制端 | 受控端 | 连接/权限 | 测试命令 | 预期 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | Linux（glibc x86_64） | 本机（--local，控制端兼受控端） | — | `bash inspect.sh --local` | 退出码 0 或 20（`--fail-on critical`），事实源 JSON 生成且通过 schema | 本地可验证 |
| C2 | WSL2（Ubuntu 22.04） | 本机（--local） | — | `bash inspect.sh --local` | 同 C1 | 本地可验证 |
| C3 | WSL1 | 本机（--local） | — | `bash inspect.sh --local` | 同 C1（WSL1 内核差异处标注意外） | 本地可验证 |
| C4 | Linux/WSL2 | Kylin V10 x86_64 | SSH key + 普通账号 | `bash inspect.sh -H <ip>` | 事实源 JSON execution_status ∈ {SUCCESS,PARTIAL}；无业务伪造 | 待现场/G0 预检 |
| C5 | Linux/WSL2 | Kylin V10 | SSH + 最小化 become（sudo） | 单指标需特权场景 | 特权指标正确采集或 UNKNOWN(PERMISSION_DENIED)，其余继续 | 待现场/G0 预检 |
| C6 | Linux/WSL2 | 无 bash/无法连接主机 | — | `bash inspect.sh -H <ip>` | 单主机→退出码 10 无业务结论；多主机→PARTIAL 取最严重 | 本地可用 fixture 模拟 |
| C7 | 任意控制端 | 无目标主机 | — | `INSPECT_FIXTURE_DIR=tests/fixtures/raw bash inspect.sh`（调试模式） | 全链路 fixture 通过（REQ-N-08） | 本地可验证 |
| C8 | 任意控制端 | 无目标主机 | — | `python -m pytest tests/test_e2e.py -q` | 全绿 | 本地可验证 |

控制端 Python 3 版本、ansible-core 版本、受控端 bash 版本、become 方式、SSH 连接参数为 G0 预检项（AE §8），**本设计不承诺版本**；实现遵循最小版本耦合（仅用 Python 3 通用标准库能力，目标以 G0 预检结果为准）。

## 10. 本地调试路径（无目标主机时）

1. **--local 自巡检**：无 `-H`/`-i` 时巡检本机（CC §3），控制端兼受控端即可跑通全链路；本机命令缺失→对应指标 UNKNOWN，链路不断。
2. **fixture 调试模式**（实现/调试专用，非用户 CLI）：环境变量 `INSPECT_FIXTURE_DIR` 指向预录输出目录时，ansible_runner 从夹具读取 probe 与指标原始输出（模拟受控端应答），不产生任何连接；启用时 stderr 输出一行"调试模式（fixture）"声明。夹具为 git 内文本文件（tests/fixtures/raw/、tests/fixtures/json/ 等），样本来自 G1 文档示例与真实 WSL 本机输出。
3. **单元级**：解析器对夹具 raw 输出；normalize 对夹具输出断言四状态与 UNKNOWN 边界；渲染对夹具 JSON 断言三报表一致性（REQ-R-08）。
4. **e2e**：tests/test_e2e.py 以 fixture 模式驱动完整 CLI→采集→normalize→JSON→stdout/xlsx/html 链路。
5. **mock inventory**：tests/fixtures/inventory/hosts.yml 用于 `-i --limit` 语义测试（不连接真实主机）。
6. 边界：fixture 模式仅在 `INSPECT_FIXTURE_DIR` 显式设置时激活；`-H` 与 fixture 同时出现时仍不连接任何主机；禁止把夹具数据写成"已验证的现网结论"。

## 11. 回滚方案

| 层面 | 机制 | 触发 | 回滚动作 |
| --- | --- | --- | --- |
| 事实源 | inspection_id 每次唯一（HR §5）；已写 JSON 不可变、不覆盖；schema_version 只增（HR §6） | 事实源被误改/重跑 | 不覆盖：重跑产生新 inspection_id；历史 JSON 保留 |
| 报表 | 报表只读 JSON 可随时重生成 | 报表模板/渲染缺陷 | 修复渲染层→从同一 JSON 重渲染，不重采集 |
| 配置 | inspect.yml / thresholds-override.yml 入 git | 配置错误（阈值/路径/unit 误配） | git revert 配置文件→重跑（错误配置产生的事实源保留并标注 provenance） |
| 版本 | generator_version 记录于 meta（HR §2）；版本 tag 化 | 发布缺陷 | 切回上一版本 tag→重跑；采集只读无受控端副作用（AE §4.4），重跑安全 |
| 数据损坏 | 原子写（tmp→fsync→rename）；JSON parse + schema 校验 | 文件损坏/半成品 | 损坏主机标 execution ERROR→该主机重跑 |
| 受控端 | 巡检只读、无修改面 | — | 无受控端回滚面（AE §4.4） |

回滚演练（T-108 AC）：fixture 下连续两次运行→断言两个 inspection_id、旧 JSON 未被覆盖、旧 JSON 可独立重渲染出三类报表。

## 12. 与 G1 契约一致性核对

| G2 冻结项 | G1 依据 | 一致性要点 |
| --- | --- | --- |
| 目录/模块边界 | AE §2 执行模型、HR §5 文件约定 | 采集→normalize→JSON→报表单向流；渲染只读 JSON |
| 采集执行 | AE §1-§7、MR §5 | raw/script+/bin/bash -lc、gather_facts:false、serial:1、最小化 become、超时 15s/10s/15s/300s、allow-list、不重试 |
| 阈值 | MR §3/§6、DC C1-C13 | 文档基线转写+外部覆盖+UNKNOWN；未锚定边界不发明 |
| CLI | CC §2-§5 | 选项表冻结；退出码 0/2/10/20；--list-metrics/--info 只读 |
| 数据契约 | HR §1-§6 | 双状态分离、metric 字段、error 枚举、原子写 |
| 报表 | RR §1-§7 | 三 Sheet、离线单文件、四状态色板、UNKNOWN 可见 |
| 脱敏 | AE §4.5、HR §1.4、DC C10/C11 | IP→`<IP>`、凭据不进 JSON/报表/事件 |

**G2 待定项（需用户 G2 批准或现场确认，本文件不写成承诺）**：ansible-core/Python/xlsxwriter 具体版本（G0 预检）、become 方式与 SSH 参数（现场）、override 覆盖值内容（现场提供，工具只提供语法与校验）、夹具样本来自真实 Kylin 输出的补全（实现期）。`docs/specs/requirements-acceptance-matrix.md` 为需求侧一致声明；`docs/specs/risk-register.md` 记录本设计的风险。
