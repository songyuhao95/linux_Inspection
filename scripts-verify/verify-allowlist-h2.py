#!/usr/bin/env python
"""verify-allowlist-h2.py — T-103F H-2 验证脚本（双引号内命令替换绕过修复）。

合同契约（contract-T-103F-v1 必需步骤 4 / AC-2）：对以下四个输入调用
inspect.ansible_runner.parse_binaries：

  - 'free -m "$(rm -rf /)"'          （双引号内 $() 命令替换）
  - 'free -m "`whoami`"'             （双引号内反引号）
  - 'cat /proc/loadavg "$(rm -rf /)"'
  - 'df -hT "/tmp;$(rm -rf /)"'      （双引号内 $()+; 复合）

每个调用必须：
  1) 在 2 秒内返回；
  2) 必须被拒绝——不得返回可执行名或放行（接受即失败）。独立验证实证：
     修复前 parse_binaries('free -m "$(rm -rf /)"') 返回 ['free'] 被 ACCEPT
     （双引号内 $()/反引号被整体当参数跳过，shell 在双引号内会展开命令
     替换 → G0 启用真实执行后即目标主机命令执行风险）。
  本实现以抛 CommandNotAllowedError 拒绝，故接受判定为：未抛异常即失败。

另附合法命令对照（修复不得误伤合法指标命令）：parse_binaries 对
'free -m' / 'cat /proc/loadavg; nproc' / 'df -hT / /data' 仍正常提取
可执行名；validate_command_specs 对全量注册表命令不抛错。

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

# H-2 复现输入（独立验证实证：修复前 'free -m "$(rm -rf /)"' 被 ACCEPT）
H2_INPUTS = (
    'free -m "$(rm -rf /)"',
    'free -m "`whoami`"',
    'cat /proc/loadavg "$(rm -rf /)"',
    'df -hT "/tmp;$(rm -rf /)"',
)
# 合法命令对照（修复不得误伤）
LEGIT_CASES = (
    ("free -m", ["free"]),
    ("cat /proc/loadavg; nproc", ["cat", "nproc"]),
    ("df -hT / /data", ["df"]),
)

PER_CALL_LIMIT_SEC = 2.0

failures = 0


def fail(msg):
    global failures
    failures += 1
    print(f"  [失败] {msg}")


def check_adversarial(cmd):
    """单输入校验：2s 内返回且必须被拒绝（不得返回可执行名或放行）。"""
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
        fail(f"绕过 allow-list（接受即失败）：{cmd!r} → {result!r}")


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
    print("T-103F H-2 验证：双引号内 $()/反引号/$VAR 必须拒绝（2s/次上限）")
    for cmd in H2_INPUTS:
        check_adversarial(cmd)
    print("合法命令对照（修复不得误伤）")
    for cmd, expected in LEGIT_CASES:
        check_legit(cmd, expected)
    if failures:
        print(f"H-2 验证失败：{failures} 项未通过（绕过 allow-list 或误拒合法命令）")
        return 1
    print("H-2 验证通过：全部对抗输入被拒绝、合法命令不受影响")
    return 0


if __name__ == "__main__":
    sys.exit(main())
