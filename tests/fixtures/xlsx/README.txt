本目录为 T-106（Excel 渲染）测试夹具。

# 非实测数据（fixture）声明

1. 本目录所有文件均为**非实测数据**：host-result-valid.xlsx 由 T-106 实现者
   以 openpyxl（requirements-dev 声明的只读校验依赖）按 render_xlsx 模块级
   常量（SHEET_NAMES / LOCAL_HEADERS / ERRORS_HEADERS / STATUS_COLORS，
   RR §3/§5）程序生成，不代表任何真实主机、真实巡检结果或真实网络。
2. 用途：
   - xlsxwriter 缺失环境（本任务按合同不安装依赖）：对夹具样本做结构断言
     （三 Sheet 名、列头、Overview 内容、RR §5 状态背景色），验证
     "模块级常量/结构契约"而不实际渲染（合同要求：缺失环境 skip 实际
     渲染但保留常量/结构断言）；
   - xlsxwriter 可用环境：真实渲染产物由 openpyxl 直接只读校验（TD §8），
     本样本作为布局参照。
3. 夹具中的 IP 一律以 <IP> 占位；不含任何凭据与秘密。
4. 样本内容对应 tests/fixtures/json/host-result-valid.json（T-104 夹具，
   只读使用）：单主机 node-fx01、单指标 local.swap.used_percent（OK）、
   execution_status=SUCCESS、阈值版本 linux-common-p0-v1。
