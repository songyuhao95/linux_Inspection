# G2 需求/验收矩阵（local 垂直切片）

- 文档 ID：requirements-acceptance-matrix
- 所属合同：contract-T-002-v1（run-20260814-001 / T-002 / phase=plan）
- 版本：v1（2026-08-15）
- 状态：G2 方案文档（待 G2 批准；需求来自 G1 已批准文档，本文件只转写不新增）
- 输入：7 份 G1 文档（docs/specs/*.md 六份 + docs/reviews/docx-source-conflicts.md，sha256 见合同 input_artifacts）

## 1. 方法与溯源约定

每条需求映射一个 G1 来源（文档 ID + 章节/指标 ID/冲突编号）与一个可执行验收方法。来源缩写：

| 缩写 | 文档 |
| --- | --- |
| PB | docs/specs/inspection-product-brief.md |
| MR | docs/specs/local-metrics-requirements.md |
| HR | docs/specs/host-result-v1.md |
| CC | docs/specs/cli-contract.md |
| AE | docs/specs/ansible-execution.md |
| RR | docs/specs/reporting-roadmap.md |
| DC | docs/reviews/docx-source-conflicts.md（冲突编号 C1–C13） |

验收命令均为实现阶段（T-10x）可执行的机器检查；"负责任务"列见 docs/specs/task-dag.md。本矩阵不发明阈值：所有判定边界均来自 MR §6 汇总表与 DC 裁决，未锚定边界一律 `UNKNOWN` 或由外部配置覆盖（MR §3）。

## 2. 组 A：采集与指标（10 个共同 P0）

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-M-01 | `local.process.present`：按 profile 进程模式（pgrep/ps）匹配；存在→OK，缺失→CRIT（故障）；无 profile 配置→UNKNOWN | MR §5.1；PB §5 | 单元测试覆盖 present/absent/无配置三路径 + 输出含 metric_id | `python -m pytest tests/test_normalize.py -q`（含 REQ-M-01..10 场景） | T-103/T-104 |
| REQ-M-02 | `local.service.active`：systemctl is-active/show ActiveState 按 unit 名；active→OK，非 active→CRIT；unit 无配置（C8）→UNKNOWN | MR §5.2；DC C8 | 单元测试覆盖枚举值 + C8 无配置路径 | 同上（test_service_active 场景） | T-103/T-104 |
| REQ-M-03 | `local.port.listening`：`ss -tlnp` 按端口过滤并核对监听进程；监听且进程匹配→OK，不监听→CRIT；模式外端口（Kafka 9092）→WARN 需确认（C7/C13 配置边界） | MR §5.3；DC C7/C13 | 单元测试覆盖 C7 样例（9093 主端口、9092 额外开放→WARN） | 同上（test_port_listening 场景） | T-103/T-104 |
| REQ-M-04 | `local.cpu.utilization`：top -bn1 + ps Top 进程；<70% 且波动 <80%→OK，持续 >80%→WARN，>90% 且伴随业务证据→CRIT；Nginx/Tomcat 层级差异（C2）不发明专属阈值 | MR §5.4；DC C2 | 单元测试覆盖分层；>90% 无业务证据采集能力时保持 WARN 并在 provenance.notes 注明（不提升 CRIT） | 同上（test_cpu_utilization 场景） | T-103/T-104 |
| REQ-M-05 | `local.cpu.load_1m`：/proc/loadavg + nproc；≤核数→OK；持续 >核数等级缺失（C5）→UNKNOWN，外部配置可覆盖 | MR §5.5；DC C5 | 单元测试覆盖 ≤核数 OK 与 >核数 UNKNOWN（missing）路径 | 同上（test_load_1m 场景） | T-103/T-104 |
| REQ-M-06 | `local.memory.available_percent`：free -m available/total×100；≥20%→OK，<10%→CRIT，10–20% 区间未定义（C4）→UNKNOWN | MR §5.6；DC C4 | 单元测试覆盖三区间与 C4 缺失边界 | 同上（test_memory_available 场景） | T-103/T-104 |
| REQ-M-07 | `local.swap.used_percent`：free Swap 行；used=0 或未配置→OK；used>0 判据冲突（C3）→UNKNOWN，外部配置可覆盖 | MR §5.7；DC C3 | 单元测试覆盖 =0→OK 与 >0→UNKNOWN（conflict） | 同上（test_swap_used 场景） | T-103/T-104 |
| REQ-M-08 | `local.filesystem.used_percent`：df -hT 按 profile 路径、多目录取最大；<75%→OK、75–85%→WARN、>85%→CRIT、>95%→故障 CRIT；Nginx/Tomcat 80% 建议线（C1）与 ES 90% 层（C6）标注差异不改变判定 | MR §5.8；DC C1/C6 | 单元测试覆盖 75/85/95 分层与 C1/C6 差异标注 | 同上（test_fs_used 场景） | T-103/T-104 |
| REQ-M-09 | `local.filesystem.inode_used_percent`：df -i；<80%→OK；≥80% 边界缺失（C5）→UNKNOWN | MR §5.9；DC C5 | 单元测试覆盖 <80 OK 与 ≥80 UNKNOWN（missing） | 同上（test_inode_used 场景） | T-103/T-104 |
| REQ-M-10 | `local.logs.key_evidence`：按 profile 日志路径与关键词 tail/grep 匹配；无可解释错误→OK；命中按产品手册判定，冲突未解决（C10）→UNKNOWN；日志不可读→UNKNOWN（非 OK） | MR §5.10；DC C10 | 单元测试覆盖 无命中 OK / 命中 UNKNOWN(conflict) / 权限不足 UNKNOWN(PERMISSION_DENIED) | 同上（test_logs_key_evidence 场景） | T-103/T-104 |

## 3. 组 B：数据契约（host-result-v1）

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-D-01 | 版本化 JSON 是唯一事实源：一次采集→一次规范化→原子写 JSON；报表只消费 JSON 不二次采集 | PB §4.4/§6；HR §1.1；RR §1 | 事实源文件经 JSON Schema 校验；渲染测试断言不触发采集调用 | `python -m pytest tests/test_render_stdout.py tests/test_render_xlsx.py tests/test_render_html.py -q` | T-104/T-105/T-106/T-107 |
| REQ-D-02 | 执行状态与业务状态分离：execution_status（SUCCESS/PARTIAL/ERROR）与 status（OK/WARN/CRIT/UNKNOWN）；技术失败不得伪装业务 CRIT | HR §1.2/§2.1/§2.2；AE §6 | 单元测试覆盖六种 执行×业务 组合；error 存在时 status 必为 UNKNOWN | `python -m pytest tests/test_fact_source.py -q` | T-104 |
| REQ-D-03 | metric 对象必填字段：metric_id/name/scope/status/raw_value/unit/threshold/evidence/provenance；字段缺失即定义不完整→UNKNOWN | HR §3.1；MR §2 | normalize 输出字段级断言 + JSON Schema required 校验 | `python -m pytest tests/test_normalize.py -q` | T-104 |
| REQ-D-04 | 阈值可追溯：每个业务状态回溯到阈值层（document-baseline/external-config/unresolved-document-conflict）+ 规则 ID + 来源锚点 | HR §3/§4；MR §3 | 单元测试断言 threshold.layer/rule_id/source_anchor 与判定来源一致 | 同上（test_threshold_traceability） | T-104 |
| REQ-D-05 | 状态判定流程固定顺序：执行失败→外部配置→文档基线→无规则/冲突→UNKNOWN | HR §4 | 单元测试覆盖优先级（外部配置优先于文档基线） | 同上（test_decision_order） | T-102/T-104 |
| REQ-D-06 | 原子写：临时文件→fsync→rename；inspection_id 唯一不覆盖历史；可选汇总索引引用各主机 sha256 | HR §5 | 单元测试模拟写入验证无半成品文件、重跑不覆盖 | `python -m pytest tests/test_fact_source.py -q`（test_atomic_write） | T-104 |

## 4. 组 C：CLI（cli-contract）

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-C-01 | 全部选项：-h/--help、-H/--hosts、-i/--inventory、--limit、--local、--all、--list-metrics、--info、-e/--excel [PATH]、--html [PATH]、--fail-on critical | CC §2 | 帮助输出含全部选项与退出码表；argparse 单元测试 | `bash inspect.sh -h` + `python -m pytest tests/test_cli.py -q` | T-101 |
| REQ-C-02 | 主机选择语义：无参数→本机（--local）；-H 逗号列表；-i+--limit；-i+--all；--local 与 -H/-i 互斥→用法错误 2 | CC §3 | 互斥与选择语义单元测试 + 退出码断言 | `python -m pytest tests/test_cli.py -q`（test_host_selection） | T-101 |
| REQ-C-03 | 退出码：0 成功 / 2 用法错误 / 10 技术执行失败 / 20 仅 --fail-on critical 时业务 CRIT；技术失败优先于业务告警；部分主机失败取最严重 | CC §4 | 以 fixture JSON 驱动退出码映射测试（0/2/10/20 全覆盖） | `python -m pytest tests/test_cli.py -q`（test_exit_codes） | T-101 |
| REQ-C-04 | --list-metrics / --info 只读本地定义，不采集不连接；未实现的中间件选择明确报"不支持"退出码 2 | CC §2/§3；PB §4.8/§4.10 | 输出含 10 个共同 P0 指标 ID；未知/不支持参数→2 | `python -c "import subprocess; o=subprocess.run(['bash','inspect.sh','--list-metrics'],capture_output=True,text=True).stdout; assert all(m in o for m in ['local.process.present','local.cpu.utilization','local.cpu.load_1m','local.service.active','local.port.listening','local.memory.available_percent','local.swap.used_percent','local.filesystem.used_percent','local.filesystem.inode_used_percent','local.logs.key_evidence'])"` | T-101 |
| REQ-C-05 | 帮助文本含：用法行、选项表、退出码表、主机选择示例、事实源与报表输出说明、脱敏声明 | CC §5 | 文本断言 | `bash inspect.sh -h | grep -F '退出码: 0 成功 / 2 用法错误 / 10 执行失败 / 20 业务告警'` | T-101 |
| REQ-C-06 | 只读巡检：不修改目标主机配置、不写业务数据、不导入凭据参数；凭据不进命令行与帮助文本 | CC §1.5/§7；PB §8.4 | 结构审查 + 采集命令 allow-list 测试（AE §4.1） | `python -m pytest tests/test_ansible_runner.py -q`（test_allow_list） | T-103 |

## 5. 组 D：执行（ansible-execution）

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-E-01 | 控制端 Linux/WSL 假定 Python 3；受控端不假定 Python：gather_facts:false，raw/script + `/bin/bash -lc` 执行 Bash | AE §1/§2；PB §2 | 生成的 playbook 文本断言（gather_facts:false、serial:1、raw/script、/bin/bash -lc） | `python -m pytest tests/test_ansible_runner.py -q`（test_playbook_generation） | T-103 |
| REQ-E-02 | 每个主机独立线程启动单主机 playbook，playbook 固定 serial:1；控制端 `--parallel` 允许 1-10（默认 10）；普通账号最小化 become；禁止 root 全程运行 | AE §1/§5；PB §2 | playbook 文本断言 + 线程上限/结果顺序测试 + become 最小化结构审查 | `python -m pytest tests/test_ansible_runner.py -q`（test_run_uses_bounded_threads_per_host、test_playbook_minimal_become_only_declared_metrics） | T-130 |
| REQ-E-03 | 能力探测：probe 命令集合（bash/pgrep/ss/free/df/...）；命令缺失→相关指标 UNKNOWN（COMMAND_NOT_FOUND）；bash 不可用→主机 ERROR | AE §3 | fixture 探针输出→能力矩阵映射单元测试 | `python -m pytest tests/test_ansible_runner.py -q`（test_capability_probe） | T-103 |
| REQ-E-04 | 超时：probe 15s；指标命令 10s（日志 15s）；单主机总时长上限 300s；超时按 TIMEOUT→UNKNOWN，不得当业务正常 | AE §3/§7；MR §5 各指标超时列 | 超时参数注入断言 + 超时路径单元测试 | 同上（test_timeouts） | T-103 |
| REQ-E-05 | 命令 allow-list：采集命令必须来自指标定义（文档锚点），禁止任意命令注入 | AE §4.1 | 未登记命令拒绝单元测试 | 同上（test_allow_list） | T-103 |
| REQ-E-06 | 输出只读：无 kill/rm/systemctl stop/写操作 | AE §4.4 | 命令集合只读性结构审查（每个命令对照 MR 数据源列） | `python -m pytest tests/test_metrics.py -q` + 结构审查 | T-101/T-103 |
| REQ-E-07 | 失败/业务分离：部分指标失败→execution PARTIAL 失败指标 UNKNOWN+error；单主机连接失败→该主机无业务结论退出码 10；全部失败/控制端失败→ERROR 退出码 10 | AE §6；CC §4 | 三场景单元测试 + 退出码断言 | `python -m pytest tests/test_ansible_runner.py tests/test_cli.py -q` | T-103/T-101 |
| REQ-E-08 | 超时/连接失败不自动重试；probe 不可达时跳过该主机后续 bundle | AE §7 | 重试计数断言（0 重试）+ callback/playbook 闸门断言 | `python -m pytest tests/test_ansible_runner.py -q`（test_playbook_contract_markers、test_no_retry） | T-103/T-130 |
| REQ-E-09 | 结果脱敏：host-result JSON/事件/HTML 中 IP 脱敏为 `<IP>`、凭据关键字脱敏、原始输出只落本地临时目录；Excel Local.ip 仅使用运行时 inventory 映射用于运维识别 | AE §4.5；HR §1.4；DC C10/C11 | 脱敏单元测试（IP/凭据/日志行）+ 报表不含明文 IP 断言 | `python -m pytest tests/test_normalize.py -q`（test_desensitization） | T-104 |

## 6. 组 E：报表（reporting-roadmap）

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-R-01 | stdout：run 摘要、主机摘要（execution_status、状态计数）、失败/未知指标列表、退出码说明；顺序先全局后逐主机 | RR §2 | 渲染输出断言（内容与顺序） | `python -m pytest tests/test_render_stdout.py -q` | T-105 |
| REQ-R-02 | UNKNOWN 与 ERROR 必须显式展示原因（missing/conflict/permission/timeout），不得静默过滤 | RR §2/§6.2 | 含 UNKNOWN 样本渲染断言 | 同上（test_unknown_visible） | T-105 |
| REQ-R-03 | Excel 三 Sheet：Overview / Local / Errors-Evidence；Local 含 host/ip/metric_id/name/raw_value/normalized_value/unit/status/threshold_rule/command，UNKNOWN 不混入 OK 计数 | RR §3 | 生成文件 Sheet 名与单元格断言（zipfile/openpyxl 只读校验） | `python -m pytest tests/test_render_xlsx.py -q` | T-106 |
| REQ-R-04 | Excel 文件名 `<inspection-id>.xlsx`；`--excel PATH` 可覆盖 | RR §3.2；CC §2 | 文件名断言 | 同上（test_filename） | T-106 |
| REQ-R-05 | HTML 离线单文件：CSS/JS 全内联、数据以 JSON 内嵌、无外部依赖可离线打开 | RR §4 | 无 `<link`/`<script src`/fetch 外链文本断言 + 内嵌 JSON 与事实源一致断言 | `python -m pytest tests/test_render_html.py -q` | T-107 |
| REQ-R-06 | HTML 布局：左导航（run 摘要/主机列表/状态筛选/中间件/监控指标筛选，选项超过 10 个时滚动）、右滚动区（主机摘要并入主机大卡片，指标卡片单列全宽且与 Excel Local 字段一致，不展开 evidence/source/provenance）、支持主机/状态/中间件/监控指标四种分组、打印友好 | RR §4 | 模板结构与占位符断言 | 同上（test_layout） | T-107 |
| REQ-R-07 | 四状态颜色与徽标：OK #2E7D32 / WARN #F9A825 / CRIT #C62828 / UNKNOWN #757575；execution_status 以徽标区分 | RR §5 | 颜色值断言（stdout 可选/HTML 必含） | 同上（test_palette） | T-105/T-107 |
| REQ-R-08 | 一致性：三类报表由同一份 JSON 渲染，同一 inspection 状态计数一致 | RR §6.1 | 同一 fixture JSON 渲染三类报表并比对计数 | `python -m pytest tests/test_e2e.py -q` | T-108 |

## 7. 组 F：NFR 与运行边界

| ID | 需求 | G1 来源 | 验收方法 | 可执行验证命令 | 负责任务 |
| --- | --- | --- | --- | --- | --- |
| REQ-N-01 | 命令可重复：所有巡检动作固定为可重复执行命令；结果只记录结论、异常证据和处理动作 | PB §8.1 | 命令集合与指标定义一一对应断言（metrics.py 定义即命令唯一来源） | `python -m pytest tests/test_metrics.py -q` | T-101 |
| REQ-N-02 | 结论明确：仅四状态；判据缺失一律 UNKNOWN 而非猜测 | PB §8.2；MR §4 | status 枚举断言（输出中不出现四状态之外值） | `python -m pytest tests/test_normalize.py -q`（test_status_enum） | T-104 |
| REQ-N-03 | 执行/业务分离：技术失败不产生业务 CRIT；业务 CRIT 默认不产生非零退出码 | PB §8.3；AE §6 | 见 REQ-D-02 / REQ-C-03 组合测试 | `python -m pytest tests/test_e2e.py -q` | T-104/T-108 |
| REQ-N-04 | 脱敏：IP/端口/路径/用户/模式保持配置边界；凭据不进 JSON、报表与事件；Excel Local.ip 的运行时 inventory 映射不回写事实源 | PB §8.4；AE §4.5 | 见 REQ-E-09 + 全链路 e2e 脱敏断言 | `python -m pytest tests/test_e2e.py -q`（test_desensitization_e2e） | T-104/T-108 |
| REQ-N-05 | 超时上限覆盖全部采集动作（探针失败按能力不足/技术失败处理） | PB §8.5；AE §3/§7 | 见 REQ-E-04 | — | T-103 |
| REQ-N-06 | 只写事实源：报表不二次采集、不修改事实源格式（版本化兼容） | PB §8.6；RR §1 | 渲染测试断言无采集调用（mock 注入） | `python -m pytest tests/test_render_stdout.py tests/test_render_xlsx.py tests/test_render_html.py -q` | T-105/T-106/T-107 |
| REQ-N-07 | 兼容性：控制端 Linux/WSL；受控端 Kylin V10（bash 4.x、systemd、不假定 Python）；组合见兼容测试矩阵 | PB §2；AE §1 | 矩阵每组合可执行 smoke 命令；fixture 模式覆盖无目标主机情形 | `bash inspect.sh --local` + `python -m pytest tests/test_e2e.py -q` | T-108 |
| REQ-N-08 | 本地调试路径：无目标主机时以 fixture 数据跑通全链路 | PB §5（本机可跑通为验收基线）；任务 scope include | e2e fixture 全链路测试 | `python -m pytest tests/test_e2e.py -q` | T-103/T-108 |
| REQ-N-09 | 回滚：事实源不可变（inspection_id 唯一、schema_version 只增）、报表可从 JSON 重生成、配置回滚（git revert） | HR §5/§6 | 回滚演练 e2e 断言（重跑不覆盖、旧 JSON 可重渲染） | `python -m pytest tests/test_e2e.py -q`（test_rollback） | T-108 |

## 8. 未决边界（G2 不裁决，转 G2 审批/外部配置）

| 项 | G1 状态 | G2 处置 |
| --- | --- | --- |
| swap>0 判据（C3） | unresolved | 默认 UNKNOWN；override 语法支持覆盖（阈值 override 文件） |
| load 持续超核数、inode≥80%（C5） | unresolved（缺失） | 默认 UNKNOWN；override 支持覆盖 |
| systemd unit 命名（C8） | unresolved（配置） | unit 名属 inspect.yml 配置边界；无配置→UNKNOWN |
| ansible-core / Python 小版本 / xlsxwriter 版本 | G0 预检待验证 | 不承诺版本；选型见 technical-design.md §8，版本以 G0 预检为准 |
| 现网阈值与文档基线差异 | 待现场核对 | 差异一律走外部配置覆盖，provenance 记录来源 |

## 9. 一致性声明

- 本矩阵需求全部可回溯到 G1 文档；未新增 G1 之外的需求与阈值。
- 每条需求均有可执行验收命令，映射到任务 DAG（docs/specs/task-dag.md）中 T-101..T-108 的 AC。
- 与 docs/specs/technical-design.md、docs/specs/risk-register.md 共享同一需求 ID 命名空间，方案/风险条目引用本矩阵 ID。
