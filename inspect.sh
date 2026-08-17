#!/usr/bin/env bash
# inspect.sh — 中间件运维巡检 CLI 入口（纯 bash 包装，无业务逻辑）
#
# 职责（docs/specs/technical-design.md §3/§4）：
#   1. 定位可用的 Python 3 解释器：python3 优先；控制端为 Windows 时
#      python3 常为 Microsoft Store 桩（无输出、退出码 49），此时回退 python；
#   2. 定位包路径（本脚本所在目录）并导出 PYTHONPATH；
#   3. exec python3 -m inspect.cli "$@"，所有参数原样透传。
#
# 参数解析/主机选择/退出码映射/编排全部在 Python 侧（inspect/cli.py），
# 本文件不包含任何解析或采集逻辑。

# 定位脚本所在目录（兼容任意 cwd 调用；CDPATH 置空避免别名干扰）
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# 定位可用的 Python 3 解释器：探针要求真实可运行（版本主号为 3）
# 失败候选（如 Windows Store 桩、版本不符）自动跳过，不输出探针噪声。
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "inspect.sh: 错误: 未找到可用的 Python 3 解释器（已尝试 python3、python）" >&2
  exit 10
fi

# 包路径：本脚本所在目录优先（inspect/ 包与后续挂接模块所在）
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "$PY" -m inspect.cli "$@"
