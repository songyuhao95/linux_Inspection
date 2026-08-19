# inspect.sh 命令行契约（cli-contract v1）

- 文档 ID：cli-contract
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- CLI 名称：`inspect.sh`（批准计划命名；控制端 Linux/WSL 入口，可执行脚本）

## 1. 总则（用户已确认的边界）

1. 无 `-H` 且无 `-i` 时**巡检本机**；`-H ip1,ip2` 指定远程主机（逗号分隔）；`-i` 走已有 inventory。
2. 控制端假定 Python 3；受控端不假定 Python（执行契约见 docs/specs/ansible-execution.md）。
3. **执行失败与业务告警退出码分离**：默认业务告警不产生非零退出；仅 `--fail-on critical` 时业务 CRIT 触发退出码 20。
4. 未实现的中间件专属检查：选择未支持的中间件参数时明确报"不支持"（错误信息 + 退出码 2），不静默忽略。
5. 所有命令为**只读巡检**：不修改目标主机配置、不写业务数据、不导入凭据参数。

## 2. 选项总表

| 选项 | 参数 | 说明 |
| --- | --- | --- |
| `-h`, `--help` | 无 | 打印帮助与退出码说明，退出码 0 |
| `-H`, `--hosts` | `ip1,ip2,...` | 巡检指定主机（逗号分隔）；与 `--local` 互斥 |
| `-i`, `--inventory` | PATH | 使用已有 inventory 文件；配合 `--limit` 选择主机 |
| `--limit` | PATTERN | inventory 主机模式（同 ansible 语义）；仅与 `--inventory` 一起使用 |
| `--local` | 无 | 显式巡检本机（默认行为）；与 `-H`/`--inventory` 互斥 |
| `--nginx` | 无 | 只巡检 Nginx 中间件（默认巡检全部已注册中间件；Nginx 进程发现见 nginx-middleware.md） |
| `--all` | 无 | 巡检 inventory 中全部主机（等价 `--limit all`） |
| `--list-metrics` | 无 | 列出已实现指标清单（ID、名称、阈值层、来源锚点），不采集不连接 |
| `--info METRIC_ID` | 指标 ID | 显示单个指标定义（数据源/单位/阈值层/来源/冲突备注），不采集 |
| `-e`, `--excel [PATH]` | 可选 PATH | 生成 Excel 报表；无 PATH 时输出到 `Path.cwd()`，有 PATH 时直接使用给定路径 |
| `--html [PATH]` | 可选 PATH | 生成离线单文件 HTML 报表；无 PATH 时输出到 `Path.cwd()`，有 PATH 时直接使用给定路径 |
| `--fail-on critical` | 无 | 任一指标业务状态为 CRIT 时以退出码 20 结束（默认：仅报告，退出码 0/10） |

> 注：`--hosts` 的短选项为 `-H`；`--help` 的短选项为 `-h`。表格以反引号分隔以避免歧义。

## 3. 主机选择语义

| 输入 | 行为 |
| --- | --- |
| （无主机参数） | 巡检本机（等价 `--local`） |
| `-H ip1,ip2` | 巡检列表中的主机；本机地址也在列表内时包含本机 |
| `-i PATH --limit PATTERN` | 从 inventory 按 pattern 选择主机 |
| `-i PATH --all` | inventory 全部主机 |
| `--local` 与 `-H`/`-i` 同时给出 | 用法错误，退出码 2，提示互斥 |
| 不支持的中间件参数（如 `--profile kafka-unknown`） | 明确报"不支持"，退出码 2 |

## 4. 退出码

| 码 | 含义 | 触发条件 |
| --- | --- | --- |
| 0 | 成功 | 巡检完成；含业务 WARN/CRIT 但未启用 `--fail-on critical`（默认行为） |
| 2 | 用法错误 | 未知选项、参数缺失、互斥选项、不支持的中间件选择 |
| 10 | 执行失败（技术） | 控制端失败、inventory 解析失败、所有主机连接失败、事实源写入失败；与业务状态无关 |
| 20 | 业务告警 | 仅当 `--fail-on critical` 启用且任一指标 status=CRIT |

规则：

- 技术失败（10）优先于业务告警（20）：执行失败时不得再产生业务结论。
- `--fail-on critical` 只响应业务 CRIT；`UNKNOWN`/`WARN` 不触发 20。
- 部分主机失败：退出码取最严重者（20 > 10 > 0），并记录于 `execution_status=PARTIAL`。

## 5. 帮助输出（`-h`/`--help` 内容约定）

帮助文本必须包含：用法行、全部选项表、退出码表、主机选择示例、事实源与报表输出说明、脱敏声明。示例：

```
用法: inspect.sh [选项]
  -h, --help               显示本帮助
  -H, --hosts ip1,ip2      巡检指定主机（逗号分隔；缺省巡检本机）
  -i, --inventory PATH     使用已有 inventory
      --limit PATTERN      inventory 主机模式（与 --inventory 搭配）
      --local              显式巡检本机（默认）
      --nginx              只巡检 Nginx 中间件
      --all                inventory 全部主机
      --list-metrics       列出已实现指标，不采集
      --info METRIC_ID     显示指标定义，不采集
  -e, --excel [PATH]       生成 Excel 报表；可选输出路径
      --html [PATH]        生成离线单文件 HTML 报表；可选输出路径
      --fail-on critical   任一指标 CRIT 时退出码 20
退出码: 0 成功 / 2 用法错误 / 10 执行失败 / 20 业务告警(--fail-on critical)
```

## 6. 用法示例

```bash
# 巡检本机，终端输出
inspect.sh

# 巡检两台远程主机并生成 Excel 与离线 HTML
inspect.sh -H 10.0.0.11,10.0.0.12 -e report.xlsx --html report.html

# 走已有 inventory，限 2 台，CRIT 时非零退出
inspect.sh -i inventory/hosts.yml --limit 'db*' --fail-on critical

# 只读查询，不采集
inspect.sh --list-metrics
inspect.sh --info local.cpu.utilization
```

## 7. 边界与安全

- 凭据不入命令行与帮助文本；`--fail-on critical` 等业务参数不得携带秘密。
- `--inventory` 路径必须存在且格式可解析，否则退出码 2（用法错误）或 10（解析失败）按第 4 节区分。
- 输出路径不存在时创建父目录；写入失败按执行失败（10）处理。
- 本契约只定义用户可见 CLI；实现细节（参数解析库、Ansible 封装）在 G2 阶段确定。
