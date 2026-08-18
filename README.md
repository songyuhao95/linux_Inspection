# linux_Inspection

项目内 Linux 中间件只读巡检工具。

## 执行路径

- `inspect.sh --local`：使用项目内 Python 3.12，直接调用本机 bash 探测和指标命令；**不调用 Ansible**。
- `inspect.sh -H <host>` / `inspect.sh -i <inventory>`：使用项目内 Python 3.12 启动项目内打包的 Ansible；不依赖系统 Python/Ansible。
- `INSPECT_FIXTURE_DIR=...`：两种模式都使用预录 fixture，零连接、零 Ansible。

## 监控模块扩展

监控模块注册在 `inspect/modules/`，统一通过 `MonitorModule` 和 `ModuleRegistry` 暴露指标。当前内置模块为 `linux_common`。以后新增中间件时，应：

1. 在 `inspect/metrics.py` 增加带版本/来源锚点的指标定义；
2. 在 `inspect/modules/` 增加模块文件并显式注册；
3. 在命令模板和解析器中补齐该模块所需的安全 allow-list；
4. 为模块增加 fixture 与测试。

仅把任意 `.sh`/`.py` 文件放入目录不会自动执行，必须显式注册并通过 allow-list 校验。
