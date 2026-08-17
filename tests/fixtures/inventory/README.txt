# tests/fixtures/inventory/ — T-103 inventory 解析测试夹具
#
# 本目录全部文件为**非实测数据**（RK-R2-06）：合成 inventory 样例，
# 仅用于 inventory 解析/选择逻辑单元验证；不代表任何真实主机或凭据。
#
# 安全说明：夹具中出现的 ansible_user / ansible_password /
# ansible_ssh_private_key_file 均为**合成占位值**，仅用于验证
# inspect/inventory.py 不读取认证变量（RK-R3-04）；真实凭据由
# ansible/ssh 原生机制管理，工具不读取。
