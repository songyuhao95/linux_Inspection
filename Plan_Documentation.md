# Plan_Documentation

status: frozen
revision: v2

## 最终目标

完成 Elasticsearch Excel 报表垂直切片：报表每条指标的 `command` 显示对应巡检手册/指标注册表中的文档采集命令；`threshold_rule` 按固定六行模板输出测量对象、规范值、单位、判定规则、声明状态和指标作用影响。保持 host-result-v1 为唯一事实源，渲染层不执行命令、不连接目标主机；Elasticsearch 20 项指标均能进入 `elasticsearch` Sheet 并保留脱敏和 UNKNOWN 语义。

## 需求约定

- 本次交付范围是 Excel 报表及其事实源命令语义；HTML 不改变布局，但可继续消费同一事实源。
- `command` 取指标注册表 `inspect/metrics.py` 的文档命令模板。采集运行时为发现端口、进程和证书生成的 shell bundle 不作为报表 command；密码、私有认证值和运行时敏感内容不得进入 command、事实源、Excel 或 Git。
- `threshold_rule` 必须为六行、固定顺序、固定标签：
  1. 测量对象：
  2. 规范值：
  3. 单位：
  4. 判定规则：
  5. 声明状态：
  6. 指标作用影响：
- 规范值优先使用事实源阈值/文档基线可表达的信息；判定规则使用当前生效的 `threshold.value`，没有规则时明确显示未定义/UNKNOWN，不发明阈值。
- 指标作用影响使用事实源已有判定说明或按指标名称生成的安全、保守说明；缺失时显示“文档未提供影响说明”，不伪造业务结论。
- 负载窗口、文件系统挂载点等现有 `evidence.details` 仍逐行展开；每一行都输出完整六行模板。
- 只在用户明确授权的测试 VM 上做只读巡检/报表生成验证，不修改目标服务、不写入目标数据。

## 项目架构

- `inspect/metrics.py`：文档命令、单位、文档基线和未知条件的注册表事实。
- `inspect/normalize.py`：将采集结果规范化为 host-result-v1；把文档 command 写入 `evidence.command`，不把动态运行 bundle 写入报表字段。
- `inspect/render_xlsx.py`：只读 host-result-v1 JSON，生成 Overview、Local、nginx、keepalived、elasticsearch、Errors-Evidence；集中生成六行 threshold_rule。
- `tests/test_render_xlsx.py`、`tests/test_elasticsearch.py`：行为测试和回归测试；现有兼容 fixture 继续有效。
- 证据与临时输出只放 `run/`/`.test-tmp/`/`out/` 等忽略路径，不把凭据写入受控文件。

## 子任务清单

1. T-ES-REPORT-RED：增加文档 command 和六行 threshold_rule 行为测试，证明当前实现不满足新合同。
2. T-ES-REPORT-GREEN：最小修改 normalize/render_xlsx，使 20 个 Elasticsearch 指标和通用指标满足行为测试。
3. T-ES-REPORT-VERIFY：运行 Excel、Elasticsearch、全量测试和 compileall；生成 fixture Excel，并在授权 VM 做只读 Elasticsearch/Excel 验证；检查脱敏与差异。

## 交付物与验收

- 修改：`inspect/normalize.py`、`inspect/render_xlsx.py`、必要的测试和规格文档。
- Excel `Local`/中间件 Sheet 的 headers 不变；每个 `threshold_rule` 恰好六个非空标签行。
- 运行：`python -m pytest tests/test_render_xlsx.py tests/test_elasticsearch.py -q`；`python -m compileall -q inspect`；随后全量 `python -m pytest -q`。
- 结果必须明确报告本地测试和授权 VM 验证是否成功；失败不得宣称通过。

## 风险与回退

- 事实源 schema 对 threshold/evidence 键集严格校验，因此不扩展 schema，仅复用已有字段，避免破坏历史事实源。
- 既有直接构造 fixture 的 command 仍按 fixture 提供值；只有 normalize 产生的事实源统一使用文档命令。
- VM 无法连接、依赖缺失或 Elasticsearch 未运行时，保留本地证据并将 VM 验证标为失败/未完成，不降低 UNKNOWN 为 OK。
