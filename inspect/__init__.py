"""inspect — 中间件运维巡检控制端包（local 垂直切片）。

模块边界与依赖方向见 docs/specs/technical-design.md §3/§4；
CLI 契约见 docs/specs/cli-contract.md；由 inspect.sh 入口以
`python -m inspect.cli` 方式调用。

包名兼容（重要，T-101 实现期发现并解决）：
本包目录名 `inspect` 与 Python 标准库 `inspect` 同名。当仓库根位于
sys.path 首位时（`python -m pytest`、`python -m inspect.cli` 等以 -m 启动
的方式会把 cwd 置于 sys.path[0]），标准库 `inspect` 会被本包遮蔽，导致
pytest、logging、traceback 等标准库消费方启动即失败（实测：
`_pytest/_code/code.py: from inspect import CO_VARARGS` → ImportError）。
目录布局（technical-design §3）与 AC 调用方式（`python -m pytest`）均为
冻结项，且本任务只允许写入 owned_paths，因此采用“吸收”策略：
包初始化时将标准库 inspect 模块对象载入 sys.modules['inspect']，并把本
目录挂为它的子包路径（__path__）。效果：

  - 任何 `import inspect` / `from inspect import X` 得到的是标准库模块，
    pytest/日志/traceback 等消费方行为不变；
  - `import inspect.cli` / `inspect.metrics` 仍解析到本包子模块；
  - `python -m inspect.cli` 与 `python -m pytest` 均可正常工作。

长寿命替代方案（若后续变更布局，需 G2 审批）：将本目录改名（如
`inspect_pkg`）并同步 inspect.sh 与 technical-design §3；本任务不自作主张
改名。此兼容层在 tests/test_cli.py 与 tests/test_metrics.py 中均有回归
（stdlib 属性可用 + 本地子模块可导入）。
"""

import importlib
import os
import sys

__version__ = "0.1.0"

_ABSORBED = False


def _abspath(p):
    try:
        return os.path.abspath(p)
    except Exception:  # 非字符串等异常条目：不参与匹配
        return None


def _absorb_stdlib_inspect() -> None:
    """将标准库 inspect 与本地包合并为一个模块对象（幂等，仅首次生效）。"""
    global _ABSORBED
    if _ABSORBED:
        return
    here = os.path.dirname(os.path.abspath(__file__))  # 本包目录（<仓库根>/inspect）
    repo_root = os.path.dirname(here)
    original_path = list(sys.path)

    # 1) 暂存当前（尚未初始化完的）本包模块，并临时将仓库根移出 sys.path，
    #    使 `import inspect` 解析到标准库文件而非本包。
    sys.modules.pop("inspect", None)
    sys.path[:] = [p for p in original_path if _abspath(p) != repo_root]
    try:
        stdlib = importlib.import_module("inspect")  # 此处拿到标准库 inspect
    finally:
        sys.path[:] = original_path

    # 2) 标准库模块对象兼任本地包载体：允许 import inspect.cli / inspect.metrics
    stdlib.__path__ = [here]
    stdlib.__version__ = __version__

    # 3) 替换注册：此后所有 `import inspect` 得到标准库模块（行为不变）；
    #    本地子模块随 `import inspect.<子模块>` 自动挂载为该对象属性。
    sys.modules["inspect"] = stdlib
    _ABSORBED = True


_absorb_stdlib_inspect()
