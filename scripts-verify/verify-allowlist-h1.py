#!/usr/bin/env python
"""verify-allowlist-h1.py — T-103F H-1 验证脚本（裸 $/反引号死循环修复）。

合同契约（contract-T-103F-v1 必需步骤 4 / AC-1）：对以下三个输入调用
inspect.ansible_runner.parse_binaries：

  - 'free -m; $(rm -rf /)'      （裸 $ 命令替换）
  - 'free -m; `whoami`'         （裸反引号）
  - 'free -m $'                 （行尾裸 $）

每个调用必须：
  1) 在 2 秒内返回（修复前 _tokenize 对裸 $/反引号死循环挂起——独立验证
     实证 parse_binaries('free -m; $(rm -rf /)') 3 秒超时无返回）；
  2) 被拒绝（本实现以抛 CommandNotAllowedError 拒绝；挂起或被接受即失败）。

另附合法命令对照（修复不得误伤合法指标命令）：parse_binaries 对
'free -m' / 'cat /proc/loadavg; nproc' 仍正常提取可执行名。

本脚本零连接、零执行、零网络、零依赖（仅标准库 + 工作树内
inspect/{ansible_runner,probe,metrics}.py，以 spec_from_file_location
独立加载，不依赖 inspect/__init__.py 是否存在）。
退出码：0=全部通过；1=任一失败（脚本整体超时上限 20s 由外部执行兜底）。
"""

import importlib.util
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# --- 包加载：与 tests/test_ansible_runner.py 同款（worktree 内
#     inspect/__init__.py 属 forbidden_paths 不可依赖；stdlib 同名吸收），
#     以 spec_from_file_location 独立加载三个模块 ---

_MODULES = {}


def _load_module(name, path):
    if name in _MODULES:
        return _MODULES[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


probe = _load_module("t103f_probe", _ROOT / "inspect" / "probe.py")
metrics = _load_module("t103f_metrics", _ROOT / "inspect" / "metrics.py")
sys.modules["inspect.probe"] = probe
sys.modules["inspect.metrics"] = metrics
ar = _load_module("t103f_ansible_runner", _ROOT / "inspect" / "ansible_runner.py")

# H-1 复现输入（独立验证实证：修复前全部挂起/超时无返回）
H1_INPUTS = (
    "free -m; $(rm -rf /)",
    "free -m; `whoami`",
    "free -m $",
)
# 合法命令对照（修复不得误伤）
LEGIT_CASES = (
    ("free -m", ["free"]),
    ("cat /proc/loadavg; nproc", ["cat", "nproc"]),
)

PER_CALL_LIMIT_SEC = 2.0

failures = 0


def fail(msg):
    global failures
    failures += 1
    print(f"  [失败] {msg}")


def check_adversarial(cmd):
    """单输入校验：2s 内返回且必须被拒绝（抛 CommandNotAllowedError）。"""
    start = time.monotonic()
    try:
        result = ar.parse_binaries(cmd)
    except ar.CommandNotAllowedError as exc:
        elapsed = time.monotonic() - start
        if elapsed >= PER_CALL_LIMIT_SEC:
            fail(f"挂起（>={PER_CALL_LIMIT_SEC:.0f}s）：{cmd!r}")
            return
        print(
            f"  [通过] {cmd!r} 在 {elapsed * 1000:.0f}ms 内被拒绝"
            f"（CommandNotAllowedError: {str(exc)[:40]}…）"
        )
        return
    elapsed = time.monotonic() - start
    if elapsed >= PER_CALL_LIMIT_SEC:
        fail(f"挂起（>={PER_CALL_LIMIT_SEC:.0f}s）后返回：{cmd!r} → {result!r}")
    else:
        fail(f"未被拒绝（接受为合法）：{cmd!r} → {result!r}")


def check_legit(cmd, expected):
    try:
        result = ar.parse_binaries(cmd)
    except ar.CommandNotAllowedError as exc:
        fail(f"合法命令被误拒：{cmd!r} → {exc}")
        return
    if result != expected:
        fail(f"合法命令可执行名提取异常：{cmd!r} → {result!r}（期望 {expected!r}）")
    else:
        print(f"  [通过] 合法命令对照 {cmd!r} → {result!r}")


def main():
    print("T-103F H-1 验证：裸 $/反引号不挂起且拒绝（2s/次上限）")
    for cmd in H1_INPUTS:
        check_adversarial(cmd)
    print("合法命令对照（修复不得误伤）")
    for cmd, expected in LEGIT_CASES:
        check_legit(cmd, expected)
    if failures:
        print(f"H-1 验证失败：{failures} 项未通过（挂起或被接受）")
        return 1
    print("H-1 验证通过：全部对抗输入即时拒绝、合法命令不受影响")
    return 0


if __name__ == "__main__":
    sys.exit(main())
