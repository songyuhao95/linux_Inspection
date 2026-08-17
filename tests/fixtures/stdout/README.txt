本目录为 T-105（stdout 终端渲染）测试夹具。

# 非实测数据（fixture）声明

1. 本目录所有文件均为**非实测数据**：由 T-105 实现者手工构造，
   不代表任何真实主机、真实巡检结果或真实网络。
2. 用途：render_stdout 渲染测试的静态输入——
   - host-result-partial.json：PARTIAL 主机，覆盖四类 UNKNOWN/ERROR 显式
     原因（conflict / missing / permission / timeout）与业务四状态混排
     （OK/WARN/CRIT/UNKNOWN），供状态计数一致性、原因展示、无颜色符号、
     零采集 mock 等测试使用；
   - host-result-error.json：ERROR 主机（AE §6：无业务结论，metrics=[]，
     executed=0/failed=3），供 HR §8 技术失败计数不掩盖与 ERROR 主机渲染
     测试使用；
   - 两个文档与 tests/fixtures/json/host-result-valid.json（T-104 交付，
     SUCCESS 样例）共享 inspection_id，可拼装"一次巡检多主机"run 级测试。
3. 夹具中的 IP 一律以 <IP> 占位；不含任何凭据与秘密；均通过
   host-result-v1 schema 语义校验（normalize.validate_host_result）。
4. 只读消费：渲染只读这些 JSON，绝不触发采集（测试以 mock 断言零采集调用）。
