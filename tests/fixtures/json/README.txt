本目录为 T-104（normalize + host-result-v1 事实源）测试夹具。

# 非实测数据（fixture）声明

1. 本目录所有文件均为**非实测数据**：由 T-104 实现者手工构造或程序生成，
   不代表任何真实主机、真实巡检结果或真实网络。
2. 用途：fact_source 读写/校验测试的静态输入（host-result-valid.json 为
   符合 host-result-v1 schema 的完整文档；host-result-corrupt.json 为
   截断损坏文件，用于损坏检测测试）。
3. 夹具中的 IP 一律以 <IP> 占位；不含任何凭据与秘密。
4. 与 tests/fixtures/raw/（T-103 预录原始输出）配合：raw/ 提供解析输入
   基准，本目录提供事实源读写基准；两目录互不覆盖。

（RK-R2-06：所有夹具文件头声明"非实测数据"；raw 输出读取时剥离首部
# 注释行。）
