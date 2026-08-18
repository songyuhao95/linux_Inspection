# Ansible 执行契约（ansible-execution v1）

- 文档 ID：ansible-execution
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案；不包含任何实现代码

## 1. 边界（用户已确认）

| 端 | 假定 | 说明 |
| --- | --- | --- |
| 控制端 | Linux / WSL，**假定 Python 3 可用** | 运行 `inspect.sh` 与 Ansible；ansible-core 版本未验证，G0 预检记录为待验证项，不写成承诺 |
| 受控端 | **不假定 Python** | `gather_facts: false`；只使用 `raw`/`script` 模块 + `/bin/bash -lc` 执行 Bash；不使用依赖受控端 Python 的模块 |

其余边界：

- 按目标顺序 `serial: 1` 执行，避免并发风暴并保证巡检顺序可复现。
- 普通账号 + **最小化 become**：仅对需要提升权限的单条命令使用 become，权限不足的指标记 `UNKNOWN` 并继续其余指标与主机。
- SSH 仅作 Ansible transport 与诊断；不维护第二套采集逻辑。
- 未验证的受控端命令能力在 G0 预检/能力探测时记录为待验证项。

### 1.1 Inventory 与认证来源

- 默认远程 inventory 优先为本地私有的 `inventory/hosts.local.ini`，其次为项目根目录的 `inventory/hosts.ini`；`-H` 可按主机组、主机名或 `ansible_host` IP 选择。
- 仓库中的 `inventory/hosts.ini` 只能包含注释形式的脱敏示例；真实控制端应在本地填写并设置 `600` 权限，或使用被忽略的 `inventory/hosts.local.ini` 配合 `-i`。
- Ansible 原生读取 `ansible_user`、`ansible_password`、密钥和 SSH 配置；inventory 解析器只读取主机名/IP 元数据，不把认证变量写入 JSON、事件或报表。
- `--local` 不调用远程 Ansible；只有 `-H`/`-i` 远程模式进入本项目 bundled Ansible 执行路径。

## 2. 执行模型

```
inspect.sh
  └─ Ansible（控制端）
       └─ per-host（serial: 1）
            ├─ capability probe（bash 可用性、/proc、free/df/ss 可用性、权限）
            ├─ 指标采集（raw/script + /bin/bash -lc 的只读命令）
            ├─ normalize（控制端本地完成）
            └─ 原子写 host-result-v1 JSON（唯一事实源）
```

- `gather_facts: false`：不在收集 facts 上花费时间与权限。
- `serial: 1`：play 级配置，逐台依次执行。
- 采集命令全部为只读巡检命令（ps/pgrep/free/df/ss/tail/grep 等），来源见 docs/specs/local-metrics-requirements.md 各指标"数据源"列；命令集合由文档锚点 + 配置边界限定。

## 3. 能力探测（probe）

- 每台主机执行前先 probe：`/bin/bash -lc 'command -v bash; command -v pgrep; command -v ss; command -v free; command -v df; ...'`。
- probe 结果决定后续采集可用性：某命令不存在 → 相关指标 `UNKNOWN`（error=COMMAND_NOT_FOUND）并继续；bash 本身不可用 → 该主机整体 `execution_status=ERROR`，记录技术失败，不产生业务结论。
- probe 超时 15s；采集命令超时 10s（日志类 15s），超时按 `TIMEOUT` 处理（`UNKNOWN` + error），不得把超时当作业务正常。

## 4. 命令执行与安全

1. **allow-list**：采集命令必须来自指标定义（文档锚点）；实现阶段只允许在契约命令集合内组合，禁止任意命令注入。
2. 不使用 `shell` 模块依赖受控端 Python；使用 `raw` 直接执行 `/bin/bash -lc '<command>'`，或 `script` 上传只读脚本（脚本内容由采集命令集合生成）。
3. 参数拼接：主机名/IP 来自 `-H`/inventory，属配置边界；命令中不出现凭据。
4. 输出只读：巡检命令不得修改受控端（无 `kill`/`rm`/`systemctl stop`/写操作）。
5. 结果脱敏：控制端 normalize 时对 IP、端口、路径、日志片段做脱敏后再写入 JSON（见 host-result-v1.md 第 3 节）；原始输出只落本地临时目录且不进报表。
6. 秘密隔离：任何密码/token 不进命令、不进 JSON、不进事件；文档中的占位凭据（`${ES_USER}` 等）绝不回填执行。

## 5. 权限模型（become）

- 默认以**普通巡检账号**执行只读命令；仅在指标明确需要特权（如读取其他用户日志）且该指标判定依赖特权数据时，对该条命令使用最小化 `become: true`。
- become 方法（sudo/su）与控制端账号属配置边界，G0 预检时由现场确认。
- 单指标权限不足 → 该指标 `UNKNOWN`（error=PERMISSION_DENIED），**继续**其余指标与主机，整体 `execution_status=PARTIAL`。
- 禁止以 root 全程运行巡检；禁止 become 提升后执行非只读操作。

## 6. 失败与业务状态分离（核心不变量）

| 场景 | execution_status | 业务 status | 退出码（cli-contract） |
| --- | --- | --- | --- |
| 全部成功 | SUCCESS | 按阈值判定 | 0（或 20 若 `--fail-on critical` 且存在 CRIT） |
| 部分指标失败（权限/超时/命令缺失） | PARTIAL | 失败指标 UNKNOWN + error | 0/20（技术失败不提升业务） |
| 单主机连接失败 | PARTIAL/ERROR | 该主机无业务结论 | 10 |
| 全部主机失败 / 控制端失败 | ERROR | 无业务结论 | 10 |

- 技术失败（连接、probe、超时、解析）**不得伪装成业务 CRIT**。
- 业务告警（status=CRIT）**默认不导致非零退出**，仅 `--fail-on critical` 时退出码 20。

## 7. 超时与重试

- probe 15s；指标命令 10s（日志 15s）；单主机总时长上限 300s。
- 超时/连接失败不自动重试（serial:1 顺序下重复执行意义有限）；G0 预检验证 ansible 连接参数（ssh 超时、ping 间隔）后确定。

## 8. 未验证项（G0 预检清单）

1. ansible-core 版本与模块可用性（`raw`/`script` 在目标 ansible 版本下的行为）。
2. 受控端 bash 版本与 `/bin/bash -lc` 兼容性（Kylin V10 默认 bash）。
3. 巡检账号的 sudo 配置与 become 方式。
4. SSH 连接参数（跳板、密钥、端口）与 inventory 格式。
5. 文档阈值与现网部署基线的核对（外部配置覆盖入口）。

以上各项在 G0 预检完成前，本契约不承诺具体数值与行为细节。

## 9. 相关文档

- 指标与阈值：docs/specs/local-metrics-requirements.md
- JSON 事实源：docs/specs/host-result-v1.md
- 退出码：docs/specs/cli-contract.md
- 来源冲突：docs/reviews/docx-source-conflicts.md
