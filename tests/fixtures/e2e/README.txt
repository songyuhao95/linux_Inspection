非实测数据（fixture）声明 — tests/fixtures/e2e/

本目录是 T-108 端到端（e2e）夹具。全部文件为合成/预录样例，**非实测
数据**（RK-R2-06 声明）：不代表任何真实主机、服务或业务状态；展示 IP
一律 127.0.0.1；不含任何凭据。指标样本内容与 tests/fixtures/raw/node-a/
（T-103 交付）一致，e2e 只验证链路与一致性，不验证业务结论。

用途（docs/runbook.md「fixture 调试模式」）：
    INSPECT_FIXTURE_DIR=<本目录> bash inspect.sh --local
  ansible_runner 从夹具读取预录输出模拟受控端应答：零连接、零执行、
  零真实 ansible-playbook（stderr 打印「调试模式（fixture）」声明，
  TD §10.2/REQ-N-08）。

布局（与 tests/fixtures/raw/ 同约定，TD §3/§5.1）：
    README.txt        本声明
    hosts.yml         e2e inventory 选择夹具（INI 格式，合成样例）
    localhost/        --local 本机巡检夹具（主机名 = inventory 主机名）
    e2e-node-1/       -i hosts.yml --limit e2e-web 巡检夹具

每主机目录：
    probe.out         能力探测预录输出（TD §5.1：11 条命令路径逐行，
                      首行 # 声明；解析为全部 available）
    <metric_id>.out   指标原始输出（首行 # 声明；可选 .stderr/.rc/.timeout）
    CONNECTION_FAILED / PROBE_FAILED   可选标记文件（模拟连接失败/探测失败）

预期计数（两主机同构）：
    4 个可执行指标（local.cpu.utilization / local.cpu.load_1m /
    local.memory.available_percent / local.swap.used_percent）→ OK；
    6 个需 profile 指标（local.process.present 等）→ UNSUPPORTED_PROFILE
    → UNKNOWN（MR §5：无 profile → UNKNOWN）；
    主机 execution_status=PARTIAL；计数 OK=4 WARN=0 CRIT=0 UNKNOWN=6，
    executed=4 failed=6。
