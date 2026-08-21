# Ansible 执行契约（ansible-execution v1）

- 文档 ID：ansible-execution
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案；不包含任何实现代码

## 1. 边界（用户已确认）

| 端 | 假定 | 说明 |
| --- | --- | --- |
| 控制端 | Linux / WSL，使用项目内 Python 3.12 和 bundled ansible-core | 运行 `inspect.sh` 与 Ansible；不依赖系统 Python/Ansible |
| 受控端 | **不假定 Python 或 Ansible** | `gather_facts: false`；所有采集任务统一使用 `raw` + `/bin/bash -lc`，只要求 SSH、bash 和指标所需命令 |

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
- 远程密码 inventory 的 host-key 策略由 runner 固定为 `ANSIBLE_HOST_KEY_CHECKING=False` +
  OpenSSH `StrictHostKeyChecking=accept-new`：允许首次连接自动登记指纹，但已知指纹变化仍失败；
  生产部署仍应按组织规则预先核验 `known_hosts`。

## 2. 执行模型

```
inspect.sh
  └─ Ansible（控制端）
       └─ per-host（serial: 1）
            ├─ capability probe（bash 可用性、/proc、free/df/ss 可用性、权限）
            ├─ 模块 bundle 采集（raw + /bin/bash -lc 的只读命令）
            ├─ normalize（控制端本地完成）
            └─ 原子写 host-result-v1 JSON（唯一事实源）
```

- `gather_facts: false`：不在收集 facts 上花费时间与权限。
- `serial: 1`：play 级配置，逐台依次执行。
- probe 是主机级连接闸门：若 probe 已报告 SSH 不可达，后续指标任务通过
  `when: inspect_probe is not unreachable` 在控制端跳过，不会为每个指标重复等待一次
  SSH 超时；该主机最终只产生一个主机级 `CONNECTION_FAILED`，无业务结论。
- 远程指标不会再为每个指标生成一个 Ansible 任务。可执行指标按
  `linux`、`nginx`、`keepalived`、`elasticsearch` 模块打包；不同 `become` 权限或
  私有环境值会拆成独立 bundle。每台主机仍按 `serial: 1` 执行，但一个模块通常只
  产生一个 SSH/raw 远程任务。
- bundle 内部为每个指标保留 `timeout N /bin/bash -lc '…'`，并输出受控的
  `INSPECT_METRIC_BEGIN/END` 标记。控制端 callback 按 `metric_id` 拆分回既有单指标
  stdout/rc，再继续执行原有分类、normalize 和事实源写入；缺少标记显式记为
  `ERROR_DATA_MISSING`，绝不默认通过。
- 采集命令全部为只读巡检命令（ps/pgrep/free/df/ss/tail/grep 等），来源见 docs/specs/local-metrics-requirements.md 各指标"数据源"列；命令集合由文档锚点 + 配置边界限定。

## 3. 能力探测（probe）

- 每台主机执行前先 probe：`/bin/bash -lc 'command -v bash; command -v pgrep; command -v ss; command -v free; command -v df; ...'`。
- probe 结果决定后续采集可用性：某命令不存在 → 相关指标 `UNKNOWN`（error=COMMAND_NOT_FOUND）并继续；bash 本身不可用 → 该主机整体 `execution_status=ERROR`，记录技术失败，不产生业务结论。
- probe、采集命令、SSH 连接和 curl 的等待时间统一由根目录 `inspect.conf` 的
  `timeout` 控制（模板默认 3s）；超时按 `TIMEOUT` 处理（`UNKNOWN` + error），
  不得把超时当作业务正常。允许配置范围为 1-60s。

## 4. 命令执行与安全

1. **allow-list**：采集命令必须来自指标定义（文档锚点）；实现阶段只允许在契约命令集合内组合，禁止任意命令注入。
2. 不使用依赖受控端 Python 的 `shell`/`script` 任务；所有采集命令使用 `raw` 直接执行 `/bin/bash -lc '<command>'`，bundle 只是把多个这种只读命令放进同一远程任务。Elasticsearch 的私有 API 凭据由控制端 Ansible Jinja `env` lookup 临时导出到 bundle 进程环境，不写入 playbook 明文，也不要求目标机安装 Python。
3. 参数拼接：主机名/IP 来自 `-H`/inventory，属配置边界；命令中不出现凭据。
4. 输出只读：巡检命令不得修改受控端（无 `kill`/`rm`/`systemctl stop`/写操作）。
5. 结果脱敏：控制端 normalize 时对 IP、端口、路径、日志片段做脱敏后再写入 JSON（见 host-result-v1.md 第 3 节）；原始输出只落本地临时目录且不进报表。
6. 秘密隔离：任何密码/token 不进命令、不进 JSON、不进事件；文档中的占位凭据（`${ES_USER}` 等）绝不回填执行。

## 5. 权限模型（become）

- 默认以**普通巡检账号**执行只读命令；仅在指标明确需要特权（如读取其他用户日志）且该指标判定依赖特权数据时，将该指标放入独立的最小化 `become: true` bundle，不会把同模块的普通指标一起提升。
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

- probe、指标命令和日志命令使用 `inspect.conf timeout`；单主机 Ansible 控制进程仍有
  独立的执行上限，避免多个指标串行执行时把每条命令的 timeout 错当成整次巡检上限。
- SSH 通过 `ConnectTimeout=<timeout>` 和 Ansible connection timeout 控制；curl 同时
  设置 `--connect-timeout <timeout>` 与 `--max-time <timeout>`。
- 超时/连接失败不自动重试（serial:1 顺序下重复执行意义有限）；bundle 内某个指标超时后记录该指标 `UNKNOWN`，继续执行同 bundle 后续指标。G0 预检验证 ansible 连接参数（ssh 超时、ping 间隔）后确定。

## 8. 未验证项（G0 预检清单）

1. ansible-core 版本与 `raw` 模块行为（目标端不使用 Python 依赖模块）。
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
