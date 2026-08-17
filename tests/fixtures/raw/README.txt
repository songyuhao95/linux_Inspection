# tests/fixtures/raw/ — 采集执行层（T-103）fixture 模式预录输出
#
# 本目录全部文件为**非实测数据**：结构化预录样例（RK-R2-06 文件头声明），
# 仅用于 ansible_runner fixture 模式（INSPECT_FIXTURE_DIR）的单元验证。
# 任何内容都不代表真实主机的现网结果，禁止把夹具数据当作已验证结论。
#
# 布局：
#   README.txt                       本声明
#   node-a/  全部命令可用的成功主机（10 指标全量预录输出）
#   node-b/  部分失败主机：pgrep 缺失（探测）、port.listening 超时标记、
#           cpu.utilization 权限不足 stderr
#   node-c/  连接失败主机（CONNECTION_FAILED 标记）
#   node-d/  能力探测失败主机（probe.out 中 bash 缺失）
#   node-e/  夹具不完整主机（仅 cpu.load_1m.out，其余指标 DATA_MISSING）
#
# 标记文件语义（ansible_runner._execute_fixture）：
#   CONNECTION_FAILED        模拟连接失败 → 主机 ERROR（无业务结论）
#   PROBE_FAILED             模拟能力探测失败
#   <metric>.timeout         模拟命令超时（按 TIMEOUT_RC=124 分类）
#   <metric>.stderr          预录 stderr（权限失败特征 → PERMISSION_DENIED）
#   <metric>.rc              预录退出码（缺省 0）
