# relay.md

## 交接入口

本文件是当前项目的开发交接说明。后续开发会话开始时，先读取本文件及其中列出的现状文件；用户可以直接发送：

> 请读取当前目录 relay.md，按照 relay.md 的指示完成工作

开发会话必须按照本文件实施，不要把本文件中的“待确认/待验证”误写成已经完成的事实。

本会话后续职责限定为：**只写文档、分析故障和维护交接说明，不直接实现本文件所列代码任务**。具体代码开发、测试、提交和推送由其他会话完成。

---

## 1. 用户最新要求

用户已明确提出两项实现要求：

1. 项目内直接携带 Python 3.12 专用运行时，项目执行时使用该专用 Python，不依赖 VM 的系统 Python 3.7。
2. `inspect.sh` 启动时自动准备当前运行所需的环境变量，执行结束后清理临时环境；用户不再需要手动设置一组 `INSPECT_*` 环境变量。

目标执行方式应尽量简化为：

```bash
cd /data/inspect/linux_Inspection
./inspect.sh --local
```

不能要求用户先执行多条 `export`/`unset` 命令。

当前不能把真实 VM 运行描述为成功；最近一次 VM 运行失败，详见第 3 节。

---

## 2. 当前项目和边界

### 2.1 已知仓库状态

- 项目：Linux 中间件巡检工具。
- 当前主要分支：`vm-validation-20260817`。
- 已推送的 `origin/main` 与该分支当前基线为提交 `4db358211aa2d9acf1dc50758ef18f3f9d3fdcc5`。
- VM 项目目录：`/data/inspect/linux_Inspection`。
- 授权 VM 仅为：
  - `node01`：`192.168.0.10`
  - `kylin01`：`192.168.0.101`
- VM 当前已知环境：Python `3.7.9`，Ansible `2.8.8`。
- 用户提供过远程账号和密码；密码是敏感信息，任何会话都不得重新输出或写入项目。

### 2.2 必须保持的安全边界

- 不使用 `sshpass`。
- 不把密码写入脚本、配置、inventory、argv、环境快照、JSON、HTML、报告、事件日志、Git 或聊天。
- 不关闭 SSH host-key 校验。
- 不把密码作为 `ANSIBLE_*_PASSWORD`、`SSHPASS` 或其他环境变量传递。
- 远程密码如需使用，只能由 Ansible 原生交互提示读取，并且必须保持在进程输入中，不落盘。
- 项目运行仍只做只读巡检，不修改目标业务配置。
- 远程真实目标继续限制为上述两个 IP；不能因为实现专用 Python 或自动环境变量而扩大目标范围。
- 报告、日志和异常信息只能保留脱敏的版本、退出码、错误类别和状态统计，不保留原始 SSH/Ansible 输出。

### 2.3 现有功能边界

现有 CLI 和事实源契约继续有效：

- 本机默认巡检；`--local` 显式本机巡检。
- `-H/--hosts` 和既有 inventory 用于远程模式。
- `gather_facts: false`。
- `serial: 1`。
- 使用 `raw`/`script` 加 `/bin/bash -lc` 执行目标端命令。
- 事实源为版本化 JSON；stdout、Excel、离线 HTML 只消费 JSON，不二次采集。
- 技术执行状态与业务指标状态分离。
- 技术失败返回 10；业务 `CRIT` 只有在 `--fail-on critical` 时返回 20。
- `OK/WARN/CRIT/UNKNOWN` 业务状态不能代替连接、探测、解析等技术状态。

---

## 3. 最近故障和已知问题

用户在 `192.168.0.101` 的 `/data/inspect/linux_Inspection` 执行了 `./inspect.sh --local`，设置了真实执行门禁后收到：

```text
RealExecutionError: Ansible 未返回结构化 callback 结果
```

随后清理运行期文件时又收到：

```text
TypeError: unlink() got an unexpected keyword argument 'missing_ok'
```

已知原因和判断：

1. 直接输入 `inspect.sh --local` 会得到“未找到命令”，因为当前目录通常不在 shell 的 PATH 中；正确调用是 `./inspect.sh --local`。这不是巡检逻辑故障。
2. runner 捕获到的 Ansible stdout 为空或不是包含 `plays` 的 JSON callback 结果。当前代码没有提供足够的脱敏 return code/错误类别，因此不能仅凭旧 traceback 确认 Ansible 的第一原因。
3. `inspect/ansible_runner.py` 和 `inspect/fact_source.py` 使用了 Python 3.8 才支持的 `Path.unlink(missing_ok=True)`。VM 是 Python 3.7.9，清理异常覆盖了原始 Ansible 失败信息。
4. `pyproject.toml` 当前声明 Python `>=3.8`，与 VM 的 Python 3.7.9 不匹配。
5. VM 的 Ansible 2.8.8 较旧，需确认其 JSON callback、当前 playbook 写法以及 `ansible.builtin.raw` 的兼容性。不要在没有实际 stderr/return code 证据时武断认定唯一原因。

开发会话必须先修复/覆盖上述问题，并新增测试，不能把 fixture 或模拟 callback 结果称为真实 VM 成功。

---

## 4. 交接给开发会话的实现任务

### 任务 A：项目专用 Python 3.12 运行时

目标：项目执行时使用项目内的 Python 3.12，而不是 `/usr/bin/python3` 或 VM 的 Python 3.7。

需要开发会话完成并记录：

1. 评估 Kylin V10 的 CPU 架构、glibc 兼容性和可执行文件布局，选择可验证的打包方式。
2. “项目内 Python”不能只创建一个依赖系统 Python 的普通 venv。必须明确以下内容之一：
   - 项目内携带可运行的 Python 3.12 解释器及其标准库；或
   - 项目内携带经过校验的 Python 3.12 运行时归档，并在部署/初始化阶段解包到项目专用目录。
3. 与 Python 解释器配套的运行时依赖必须一致，包括 Ansible 控制端依赖以及当前项目需要的 YAML、报表和其他 Python 包。不能使用 Python 3.12 启动项目，却调用系统 Python 3.7 下的 `ansible-playbook`。
4. `ansible-playbook` 必须从同一套专用运行时调用，优先使用等价于 `专用python -m ansible` 的方式或项目内 wrapper；不得静默回退到系统 Ansible。
5. 运行时包必须有版本清单和校验值。若二进制体积不适合普通 Git，开发会话必须明确采用的仓库发布物、Git LFS 或其他已批准分发方式，不能只在文档中假设 VM 会自行联网下载。
6. 启动时检测专用 Python 是否存在、可执行、版本是否为 3.12.x；不满足时给出明确的执行失败提示并返回技术失败码 10，不能偷偷使用系统 Python。
7. 明确 Python 3.12 与选定 ansible-core 版本的兼容矩阵；Ansible 2.8.8 不应被默认视为兼容 Python 3.12。
8. 增加离线/无网络场景说明：运行时已在项目中时不应临时从互联网安装依赖。

建议涉及文件（由开发会话按实际方案增删）：

- `inspect.sh`
- `pyproject.toml`
- `requirements.txt`
- `requirements-dev.txt`
- 新增 `runtime/`、`vendor/` 或 `tools/` 下的专用运行时和启动辅助文件
- `docs/local-vm-deploy.md`
- `docs/g0-real-vm.md`
- 相关测试目录

### 任务 B：自动环境变量和生命周期清理

目标：用户无需手动设置当前真实执行所需的门禁和运行变量。

实现要求：

1. `inspect.sh` 根据参数判断本机/远程模式，并在本次子进程生命周期内准备必要变量。
2. 本机真实模式应自动准备等价于：
   - `INSPECT_ENABLE_REAL=1`
   - `INSPECT_ENABLE_LOCAL_REAL=1`
   - 不设置 `INSPECT_REMOTE_USER`
   - 不设置 `INSPECT_ASK_PASS`
3. 远程模式只能自动设置非秘密运行开关和项目配置允许的非秘密账号信息；不得自动生成、保存或传播密码。远程交互密码仍必须由 Ansible 原生 prompt 获取。
4. 明确自动环境变量的优先级：
   - 启动脚本设置的内部运行变量；
   - 用户显式传入的非秘密配置；
   - 不得让用户环境中的密码变量污染 Ansible 子进程。
5. 运行结束、异常退出和信号终止都要执行清理。不能依赖 `exec` 后才会执行的 shell `EXIT` trap；应测试正常结束、异常结束和 Ctrl-C/TERM 路径。
6. 由于脚本通常是独立进程，环境变量不应回写父 shell。仍需通过测试证明父 shell 环境不发生污染；若脚本支持被 `source`，必须拒绝或提供安全的清理行为。
7. 自动设置不能绕过目标白名单、命令 allow-list、结构化 callback 校验或安全门禁。
8. 不把完整环境变量快照写入日志或报告；测试中只能使用无秘密的哨兵值。
9. `ANSIBLE_PASSWORD`、`ANSIBLE_NET_PASSWORD`、`SSHPASS` 等潜在密码变量必须从传给 Ansible 的环境中删除。
10. 保持 `shell=False`，不得把自动变量拼接到 shell 命令字符串中。

### 任务 C：修复 Python/Ansible 故障诊断链

1. 将运行期删除逻辑改为兼容 Python 3.7 的写法，或确保专用 Python 路径永远不会触发旧解释器；推荐仍删除 `missing_ok=True` 依赖，避免错误清理掩盖真实故障。
2. 空 stdout、非法 JSON、Ansible 非零退出和 callback 加载失败必须分别给出脱敏错误类别、return code 和建议检查项。
3. 不输出完整 stderr、原始 callback、密码、环境值或可能包含敏感日志的命令输出。
4. 诊断信息必须能区分至少：
   - 专用 Python 缺失/版本不符；
   - Ansible 可执行文件缺失；
   - callback 不可用或未返回结构化 JSON；
   - playbook/module 解析失败；
   - 本机命令执行失败；
   - 运行超时；
   - 运行期文件清理失败。
5. 保证清理异常不会覆盖主异常；如清理失败，只能作为附加脱敏诊断记录。

### 任务 D：测试和文档

必须新增或更新测试，至少覆盖：

- 专用 Python 3.12 检测成功、缺失、版本错误；
- 不调用系统 Python/系统 `ansible-playbook` 的断言；
- 自动环境变量设置；
- 正常退出、异常退出、信号退出后的清理；
- 父 shell 环境不被污染；
- local 模式不带远程账号、密码或 `--ask-pass`；
- 远程模式目标白名单仍有效；
- 密码变量不会进入 Ansible 子进程环境、argv、JSON、HTML 或报告；
- Python 3.7 兼容清理路径；
- Ansible 空 stdout、非法 callback、非零 return code 的分类；
- 默认 fixture 测试仍然零连接；
- 全量 pytest 和静态秘密扫描。

文档至少更新：

- `docs/local-vm-deploy.md`：如何获取/校验项目专用 Python 3.12，如何在两台 VM 使用，运行时目录和回滚方式；
- `docs/g0-real-vm.md`：不再要求用户手动 export 门禁变量，说明脚本自动设置范围、清理行为、失败码和诊断方式；
- 如 CLI 或运行边界发生变化，更新相应规格文档，但不要把未经测试的 VM 结果写成成功。

---

## 5. 推荐实现策略（供开发会话参考）

### 5.1 Python 运行时

优先采用“项目目录内的已校验 Python 3.12 运行时 + 同一运行时的依赖包”方案，而不是在 VM 执行时联网安装。具体目录名可以由开发会话决定，但必须满足：

- 可由 `inspect.sh` 相对于自身路径定位；
- 不依赖当前工作目录；
- 不依赖用户 PATH；
- 版本和 hash 可检查；
- `ansible-playbook` 与 Python 项目使用同一运行时；
- 失败时不回退到系统 Python。

若 Kylin V10 的系统库无法运行通用 Python 3.12 二进制，开发会话必须在 relay 追加经过验证的兼容打包方案和停止条件，不能用未经验证的静态二进制冒充完成。

### 5.2 启动环境

建议把 `inspect.sh` 设计为独立进程 wrapper：

1. 计算项目根目录；
2. 定位并校验专用 Python；
3. 构造仅供本次子进程使用的环境；
4. 根据 `--local`/默认本机或远程参数设置必要的真实执行开关；
5. 启动 Python CLI；
6. 保存退出码；
7. 清理运行期变量和临时文件；
8. 以原退出码退出。

不要在源码中写入任何密码，也不要通过脚本自动把密码设置到环境变量。自动设置只应覆盖非秘密运行开关和专用运行时路径。

### 5.3 真实执行默认值

这是一个需要开发会话明确写入测试和文档的行为变化：目前 runner 使用显式环境门禁；用户要求 wrapper 自动设置门禁。建议只在 `inspect.sh` 这个受控入口自动开启：

- `./inspect.sh --local`：自动开启本机真实执行；
- 远程 `-H`/inventory：自动开启真实执行，但账号来源必须是非秘密配置或已存在的安全认证配置；如果需要密码，仍然只使用交互 prompt；
- 直接调用 Python 模块时保留原始显式门禁，防止绕过 wrapper；
- fixture 模式如果显式指定，不能被自动 real gate 覆盖；
- 不因自动设置而扩大 IP 白名单或启用 become。

如果开发会话选择不同策略，必须在 `relay.md` 和相关文档中写明理由，并补测试。

---

## 6. 交接开发顺序

开发会话按以下顺序执行：

1. 读取本文件、`inspect.sh`、`inspect/ansible_runner.py`、`inspect/fact_source.py`、`pyproject.toml`、`requirements*.txt`、现有 runner 测试和两份 VM 文档。
2. 先确定 Python 3.12 运行时/Ansible 依赖打包方案和 Kylin V10 兼容性；不要先写启动逻辑再临时决定运行时。
3. 先补测试，再实现专用运行时探测和 wrapper 环境生命周期。
4. 修复清理和 callback 诊断链。
5. 运行 focused tests、fixture e2e、全量 pytest、静态秘密/命令扫描和 `git diff --check`。
6. 只有在本地验证通过后，才由有权限的会话向两台授权 VM 部署/测试。
7. VM 结果分别记录，失败必须记录为 blocked/failed，不能把模拟结果填成成功。
8. 开发会话完成后更新本文件中的“实施状态”和“待办”，并在交接摘要中列出实际改动文件、测试命令、结果和未决问题。

---

## 7. 受保护路径

未经单独授权，不要修改以下内容：

- `linux-docx/`
- README 中与历史合同绑定的部分
- 历史合同 `contracts/contract-T-001-v1.md` 至 `v4.md`
- `run/events.ndjson`
- `.claude/` 会话和审计文件
- 已封存合同对应的历史报告

如果实现需求需要新增合同、修订规格或改变退出码/安全边界，先在 relay 和文档中记录变更理由，再由用户/主会话确认；不要悄悄改动历史事实。

---

## 8. 验收条件

任务只有同时满足以下条件才可以声称完成：

- `./inspect.sh --local` 不需要用户手动 export 环境变量；
- 实际使用项目内 Python 3.12，并能证明没有调用系统 Python 3.7；
- Ansible 控制端依赖和 Python 项目来自同一专用运行时；
- 缺失专用运行时时明确失败，不静默降级；
- 本机和远程安全门禁、目标白名单、命令 allow-list、密码隔离仍然有效；
- stdout callback 可解析，原始 Ansible 错误不再被清理异常覆盖；
- 运行结束后临时变量/运行文件按约定清理；
- focused tests、fixture e2e、全量 pytest 和静态扫描通过；
- 两台授权 VM 的真实运行结果分别有脱敏证据；
- JSON、终端、HTML（以及依赖已具备时的 Excel）均只消费事实源；
- 未提交密码、原始日志、环境快照或未经验证的成功结论。

---

## 9. 实施状态

截至本文件创建时：

- [x] 已记录 Python 3.7.9 与项目 `>=3.8` 不匹配。
- [x] 已记录 `missing_ok=True` 清理兼容性问题。
- [x] 已记录 Ansible 2.8.8 callback/模块兼容性待查。
- [x] 已记录用户要求项目专用 Python 3.12。
- [x] 已记录用户要求启动脚本自动设置并清理环境变量。
- [x] 已创建本交接文件。
- [ ] 项目专用 Python 3.12 运行时尚未实现。
- [ ] 自动环境变量 wrapper 尚未实现。
- [ ] callback/清理故障尚未在 VM 上重新验证。
- [ ] 两台 VM 尚未产生新的真实成功证据。

开发会话必须在完成后更新本节，不要删除历史故障记录。
---

## 10. 2026-08-17 Session Analysis Record

### 10.1 Session boundary

This session follows the boundary declared at the top of this relay: it only reads the current state, analyzes failures, and maintains the handoff. It did not implement source code, modify tests, run VM/SSH/Ansible, create a commit, or push Git. Code implementation, testing, and real VM validation remain the responsibility of an authorized development session.

### 10.2 Pipeline and self-test status

- `node "C:/Users/SYH/.assembly-development/scripts/self-test.mjs"`: passed; `30/30` checks passed.
- Current workflow projection: `run-20260814-001`, phase `VERIFYING`.
- Recorded human gates: `G1=approved`, `G2=approved`; the current projection contains no evidence of G3/G4 approval.
- `run/reports/G0-real-vm.md` still records a blocked result and must not be used as evidence of successful execution on either VM.
- This session did not write `run/events.ndjson` and did not change historical contracts or historical reports.

### 10.3 Read-only implementation review

As of 2026-08-17, the new requirements in section 1 are still not implemented. The current evidence is:

1. `inspect.sh` still probes `python3`/`python` from the user `PATH` and only checks that the major version is 3. It does not locate, verify, or force a project-local Python 3.12 runtime, and it does not reject a system-Python fallback.
2. `inspect.sh` still directly `exec`s the Python CLI. It does not set `INSPECT_ENABLE_REAL` or `INSPECT_ENABLE_LOCAL_REAL` based on mode, and there is no verified wrapper lifecycle cleanup or signal-path coverage.
3. `inspect/ansible_runner.py::build_playbook_argv()` still constructs a bare `ansible-playbook` command. Real execution therefore remains dependent on the control host `PATH`; there is no evidence that Ansible and the project code use one dedicated runtime.
4. The real-execution environment currently removes only `ANSIBLE_PASSWORD`, `ANSIBLE_NET_PASSWORD`, and `SSHPASS`. The required precedence rules, parent-shell isolation, and normal/error/signal cleanup behavior do not yet have new implementation evidence.
5. `inspect/fact_source.py` still uses `Path.unlink(missing_ok=True)`. This is incompatible with the recorded Python 3.7.9 VM environment and can still mask the original Ansible failure.
6. `pyproject.toml` still declares `requires-python = ">=3.8"`. `requirements.txt` and `requirements-dev.txt` remain dependency declarations, not an offline-distributable Python 3.12 plus Ansible runtime.
7. `docs/local-vm-deploy.md` and `docs/g0-real-vm.md` still contain the old manual `export`/`unset INSPECT_*` flow. They must not be rewritten as automated until the wrapper is implemented and verified.

### 10.4 Current real-validation conclusion

Fixture output and local static review must not be written as real VM success. The existing `run/reports/G0-real-vm.md` records:

- `node01` (`192.168.0.10`): blocked by `HOST_KEY_UNCONFIRMED`.
- `kylin01` (`192.168.0.101`): blocked by `AUTHENTICATION_UNAVAILABLE`.
- No project files were written to either VM, Ansible was not installed, no inspection was executed, and no password was entered or saved.

The recovery prerequisites remain: an administrator must confirm the `node01` host key in a secure terminal and provide an approved SSH key/agent or an interactive TTY for both authorized VMs. No session may bypass this with password arguments, password environment variables, `sshpass`, or disabled host-key verification.

### 10.5 Handoff order for the next development session

1. Record and settle the Kylin V10 architecture, glibc compatibility, executable layout, Python 3.12 archive/distribution method, and runtime hashes in the relay and design documents. Do not start wrapper implementation without a verifiable runtime plan.
2. Add tests first: dedicated-Python detection, same-runtime Ansible invocation, missing/version-error failures, environment precedence, parent-shell isolation, normal/error/signal cleanup, password isolation, callback classification, and Python 3.7 cleanup compatibility.
3. Implement the `inspect.sh` wrapper and same-runtime Ansible invocation. Preserve fixture priority, target allow-list, command allow-list, native interactive password handling, and `shell=False`.
4. Repair the diagnostic chain so it distinguishes dedicated-Python, Ansible executable, callback/JSON, playbook/module, command, timeout, and cleanup failures. A cleanup error may only be an additional sanitized diagnostic and must not replace the primary error.
5. Update deployment/G0 documentation and this relay's implementation status. Only after local verification may an authorized session validate the two VMs separately and record sanitized evidence for each.
6. If the selected Python 3.12 binary cannot run on Kylin V10, append the actual failure evidence, a compatible packaging alternative, and a stop condition to this relay. Do not mark the system Python 3.7 or an unverified static binary as complete.

### 10.6 Session conclusion

This session completed handoff review and risk clarification, not implementation delivery. The project remains in the state: project-local Python 3.12, automatic environment wrapper, callback/cleanup repair, and real VM success evidence are all still outstanding.


## 11. 2026-08-17 Implementation Session Update

The user explicitly authorized implementation and GitHub synchronization after the prior read-only handoff. The T-109 contract was sealed as `sha256:4a0bbabc5a0f450625dbec9e65d08f995e840d21103710efb1c4bf37fcc34c49`.

### 11.1 Delivered changes

- `inspect.sh` now runs as a standalone process, refuses `source`, creates and removes a wrapper-owned sentinel, handles normal/error/signal exits, gives fixture/query mode precedence, scopes non-secret gate variables to the child, removes common password environment variables, and never falls back to PATH Python for real execution.
- Real execution requires `runtime/bin/python3.12`, verifies Python `3.12.x`, exports `INSPECT_RUNTIME_ROOT`, and fails closed with exit code 10 when the dedicated runtime is absent or mismatched.
- `inspect/runtime.py` validates the runtime manifest, relative path, executable bit, optional SHA-256, and probed version. `inspect/ansible_runner.py` launches Ansible through the same interpreter via `python3.12 -m ansible.cli.playbook`, strips password variables, sanitizes callback diagnostics, and preserves cleanup diagnostics without replacing the primary error.
- `inspect/fact_source.py` no longer uses `Path.unlink(missing_ok=...)`; `pyproject.toml` is constrained to Python `>=3.12,<3.13`; requirements and offline runtime documentation were updated.
- `tools/build-runtime.sh` materializes an approved offline runtime archive only; it performs no network install. `runtime/manifest.json` intentionally remains `status=not-built` until an approved Linux Python 3.12 archive is supplied.
- Added runtime/wrapper regression tests and callback/cleanup tests.

### 11.2 Verification evidence

- `node "C:/Users/SYH/.assembly-development/scripts/self-test.mjs"`: passed, `30/30`.
- Focused suite: `python -m pytest tests/test_runtime.py tests/test_inspect_wrapper.py tests/test_ansible_runner.py tests/test_fact_source.py -q`: passed with one skipped Bash-dependent wrapper execution test on this Windows control host. The skip is the Bash-dependent wrapper execution test because Bash is not installed on this host.
- `python -m compileall -q inspect tests`: passed.
- `git diff --check`: passed.
- Full `python -m pytest tests/ -q` cannot pass on this host without Bash and without the approved Linux runtime; the existing CLI/E2E Bash subprocess tests fail with `FileNotFoundError`, and legacy Windows real-runner tests exercise behavior that is intentionally now fail-closed. These are environment/contract limitations, not evidence of real VM success.

### 11.3 Release/validation boundary

No VM/SSH/Ansible remote execution was attempted. The checked-in runtime is metadata plus an offline materializer, not a Linux binary. Before real execution, an administrator must provide and verify a compatible Python 3.12 archive with Ansible dependencies, populate `runtime/`, then independently validate the two authorized VMs. Existing G0 evidence remains blocked for `node01` and `kylin01`; no G3/G4 approval is inferred.

This update does not modify `run/events.ndjson`, `.claude/`, historical reports, or historical contracts.

## 12. 2026-08-17 Bundled Ansible Update (T-110)

用户确认允许将当前分支推送到 `origin`。在原 T-109 项目内 Python 3.12
runtime wrapper 基础上完成 T-110：Ansible control-side 依赖也必须位于项目
runtime 内，真实执行固定为 `runtime/bin/python3.12 -m ansible.cli.playbook`。

已完成：

- 封存合同：`contract-T-110-v1`，seal hash 为
  `sha256:c2877dfead19ba9804b7793965c622f9424f2af59e52c9a35be400e682371341`。
- `inspect/runtime.py` 校验 manifest、Python 3.12、`ansible.cli.playbook`、
  项目内 site-packages 和 collections 路径；缺失/越界/导入失败均 fail closed。
- `inspect/ansible_runner.py` 清理继承的 Python/Ansible 环境变量，只向子进程
  注入项目 runtime 的 Ansible 路径；不再依赖系统 `ansible-playbook`。
- `tools/build-runtime.sh` 改为离线校验并物化 Python + ansible-core bundle，
  不联网、不调用包管理器，并写入 Python 与 Ansible bundle hash。
- 新增 `runtime/ansible/README.md`、`runtime/ansible/requirements.lock`，
  更新 runtime、VM 部署文档和回归测试。

验证结果：

- assembly self-test：30/30 通过。
- T-109/T-110 focused pytest（使用项目内临时目录规避本机 Temp 权限问题）：
  `132 passed, 1 skipped`。
- `runtime/manifest.json` 仍为 `not-built`，因为当前工作区没有经审批的 Linux
  Python 3.12 + Ansible 离线归档；没有执行 VM、SSH 或远程 Ansible。
- `run/events.ndjson` 与 `.claude/` 为受保护/既有工作区变更，未纳入本次提交。

下一步：运行 `tools/build-runtime.sh` 物化经过审批的离线归档，复核 manifest
hash 后再进行真实目标机验证；本次完成后将两个本地提交一起推送至 `origin`。

## 13. 2026-08-17 Push Completion

The user explicitly confirmed the push to `origin`. Commits `ae07794` (project-local
Python 3.12 wrapper) and `8b29d05` (bundled Ansible enforcement) are now
published on `origin/codex/python312-runtime-wrapper`. The only remaining
working-tree changes are the pre-existing protected `run/events.ndjson` and
untracked `.claude/`; neither was included in the commits.

## 14. 2026-08-17 Kylin VM runtime-missing diagnosis

### 14.1 User-provided VM evidence

On `kylin01` (`192.168.0.101`), the user cloned the GitHub repository into:

```text
/data/inspect/linux_Inspection
```

They ran:

```bash
chmod +x inspect.sh
bash inspect.sh --local
```

The wrapper returned:

```text
inspect.sh: execution failed: project-local Python 3.12 is missing; system Python fallback is forbidden
```

### 14.2 Formal failure classification

Classify this incident as:

```text
DEPLOYMENT_ARTIFACT_MISSING
```

This is not an Ansible business failure, callback failure, SSH failure, target-command failure, or metric result. `inspect.sh` stopped before starting the Python CLI and before invoking Ansible.

The wrapper intentionally resolves the runtime relative to itself:

```text
/data/inspect/linux_Inspection/runtime/bin/python3.12
```

The cloned source repository contains the runtime contract, resolver, materializer, and manifest placeholder, but it does not contain the materialized Linux Python 3.12 binary or bundled Ansible tree. `runtime/manifest.json` remains an intentional `status=not-built` state. Therefore the exit code 10 is expected fail-closed behavior until an approved offline runtime archive is materialized.

Do not fix this by using the VM's system Python 3.7, system Ansible 2.8.8, PATH `ansible-playbook`, `pip install`, `ansible-galaxy`, `sshpass`, or by manually changing the manifest to `built`.

### 14.3 Required next-session actions

1. Confirm the checkout is based on the current `origin/main` containing T-109/T-110, not the historical `vm-validation-20260817@4db3582` baseline.
2. Obtain an approved offline archive whose root contains:

   ```text
   bin/python3.12
   ansible/site-packages/ansible/
   ansible/collections/
   ```

3. Record and verify the archive SHA-256, exact Python 3.12 patch version, exact ansible-core version, CPU architecture, and glibc compatibility.
4. Run `tools/build-runtime.sh <approved-archive>` in a target-compatible Linux environment. Do not use network installation or system packages.
5. Verify `runtime/manifest.json` is generated as `built`, with matching non-null Python and Ansible bundle hashes.
6. Verify `runtime/bin/python3.12` and `ansible.cli.playbook` import successfully from the project runtime, not from system/user site-packages.
7. Only then run `./inspect.sh --local` on each authorized VM without manual `INSPECT_*` exports.
8. Record per-VM sanitized exit codes, runtime versions/hashes, execution/metric counts, JSON/HTML evidence, and failure categories. A missing archive remains `blocked`; it is not a successful VM smoke.

### 14.4 Evidence status

- `kylin01`: blocked before Python/Ansible execution by missing project-local runtime.
- `node01`: no new evidence in this incident.
- No real local inspection result was produced by this run.
- No business metric status can be inferred.
- No password or credential was requested, stored, or included in the evidence.

This section records the user's actual VM output and must not be rewritten as a successful execution. The next development/deployment session owns runtime artifact preparation and VM validation; this session remains limited to documentation and fault analysis.

## 15. Project-local runtime materialized (2026-08-17)

The approved offline x86_64 Linux runtime was normalized and materialized into the working tree for deployment. The source archive was the official CPython 3.12.14 Linux x86_64 standalone build; Ansible dependencies were bundled from offline wheels with ansible-core 2.18.9. No network installation, system Python, system Ansible, or target connection was used.

Sanitized artifact metadata:

```text
runtime status: built
Python build: 3.12.14
Python SHA-256: 8f9781a98200d9ecda7e00464e4c64b1327abae788ae8e6979d5c859311410c7
ansible-core: 2.18.9
Ansible bundle SHA-256: 32d6eca4cbcb7cd79d8dae0602ec12c976cfc83ac795dafeb16bc9f0516d5416
platform: Linux x86_64; target glibc compatibility remains to be verified on Kylin V10
```

The runtime bundle is intentionally symlink-free so it can be transferred from the Windows development host; the Linux materializer and target checkout must still verify executable mode and ELF/glibc compatibility. The wrapper now uses `runtime/bin/python3.12` for real, fixture, and query modes and no longer searches `PYTHON3`, `python3`, or `python` on `PATH`. It also replaces inherited `PYTHONPATH` with the project source directory.

This is deployment-artifact evidence only. `kylin01` remains `DEPLOYMENT_ARTIFACT_MISSING` until the materialized runtime is transferred or pulled and successfully executed there; `node01` has no new VM evidence. No VM smoke success is claimed by this section.
