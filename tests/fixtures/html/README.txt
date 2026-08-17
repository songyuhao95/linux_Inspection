本目录为 T-107（离线单文件 HTML 渲染）测试夹具。

# 非实测数据（fixture）声明

1. 本目录所有文件均为**非实测数据**：由 T-107 实现者手工构造或程序生成，
   不代表任何真实主机、真实巡检结果或真实网络。
2. 用途：render_html 渲染测试的静态输入。
   - multi-host.json：同一 inspection 的 3 主机（node-fx01/02/03）文档数组，
     覆盖四业务状态（OK/WARN/CRIT/UNKNOWN）、SUCCESS/PARTIAL 执行状态、
     UNKNOWN 冲突（unresolved-document-conflict）与权限错误
     （error PERMISSION_DENIED），用于宏观卡片/主机详情/导航/过滤/
     色板/打印友好等渲染期断言。
3. 夹具中的 IP 一律以 <IP> 占位；不含任何凭据与秘密。
4. 转义与注入测试（<script> 载荷、HTML 特殊字符、</script> 越界）在
   tests/test_render_html.py 内基于本夹具动态构造，不固化恶意样本文件。
5. 与 tests/fixtures/json/（T-104 事实源读写夹具）互不覆盖：本目录
   提供渲染层输入基准，json/ 提供事实源持久化基准。

（RK-R2-06：所有夹具文件头声明"非实测数据"；raw 输出读取时剥离首部
# 注释行。）
