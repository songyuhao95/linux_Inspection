"""inspect/inventory.py — 主机选择与 inventory 解析（T-103）。

职责（docs/specs/technical-design.md §4 inventory.py 行 + cli-contract §3）：
  - `-H group-or-ip[,group-or-ip...]` → 优先复用项目内
    `inventory/hosts.ini`，按组名/主机名/IP 传给 Ansible；缺少默认文件时
    保留临时 inventory 兼容路径；
  - `--local` → 临时 inventory：`localhost ansible_connection=local`
    （控制端兼受控端，TD §10.1 / 兼容矩阵 C1）；
  - `-i PATH` → 解析已有 inventory（严格 INI 子集），`--limit PATTERN` /
    `--all` 选择主机（同 ansible 语义子集）；inventory 文件本身不改写；
  - 输出：HostSelection（inventory 文件路径 + 主机列表 + limit），
    供 cli 编排 → ansible_runner 执行。

错误语义（cli-contract §4/§7，TD §4 inventory.py 行）：
  - inventory 路径不存在 → 用法错误（退出码 2）；
  - inventory 解析失败（格式非法/无任何主机/limit 无匹配/不支持的
    limit 语法）→ 执行失败（退出码 10），**绝不静默跳过**；
  - `-H` 主机列表为空 → 用法错误（退出码 2）。

安全边界（RK-R3-04 / AE §4.3）：本模块**不读取任何凭据**——解析
inventory 时仅提取主机名与 ansible_host（用于展示 IP），
ansible_user / ansible_ssh_private_key_file / ansible_password 等
认证变量一律忽略（不进入任何结果对象）。inventory 原文件会原样交给
项目内 Ansible，由 Ansible 原生机制读取认证变量；本模块不把凭据写入
结果对象、JSON、事件或报表；`[group:vars]` 段整体跳过。

严格 INI 子集（本版本支持，超出即解析错误）：
  - `[组名]` 段、`[组:vars]` 段（内容跳过）、`[组:children]` 段（组级联）；
  - 主机行：`主机名 [key=value ...]`（仅取 ansible_host，其余忽略）；
  - 整行 `#` 注释与空行；不允许行内注释、制表符缩进、`-` 排除主机。
"""

from __future__ import annotations

import fnmatch
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# cli-contract §4 退出码
EXIT_USAGE = 2
EXIT_EXEC = 10

# TD §3 目录布局：.runtime/ 临时 inventory/playbook/raw 输出（.gitignore）
RUNTIME_DIR_NAME = ".runtime"
DEFAULT_INVENTORY_RELATIVE_PATH = Path("inventory") / "hosts.ini"

# inventory 解析错误分类消息前缀
_MSG = {
    "missing": "inventory 文件不存在",
    "unreadable": "inventory 文件无法读取",
    "parse": "inventory 解析失败",
    "empty": "inventory 无任何主机",
    "limit_syntax": "不支持的 --limit 语法",
    "limit_nomatch": "--limit 未匹配任何主机",
    "hosts_empty": "-H 主机列表为空",
}


class InventoryError(Exception):
    """inventory 层错误（cli-contract §4：用法错误 2 / 执行失败 10）。"""

    def __init__(self, message: str, *, exit_code: int = EXIT_EXEC):
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


@dataclass
class HostEntry:
    """单个受控主机（不含任何认证/凭据信息，RK-R3-04）。"""

    name: str      # inventory 主机名 / -H 的 IP / localhost
    ip: str        # 展示用 IP（ansible_host 声明则用之，否则等于 name）

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "ip": self.ip}


@dataclass
class HostSelection:
    """主机选择结果：inventory 文件 + 主机列表 + limit（供执行层消费）。"""

    kind: str                        # "local" | "hosts" | "inventory"（cli 语义）
    inventory_file: Path             # 临时生成的（-H/--local）或用户提供的（-i）
    hosts: List[HostEntry] = field(default_factory=list)
    limit: Optional[str] = None      # -i 模式的 limit 模式（None/“all”→全部）


# --------------------------------------------------------------------------
# 严格 INI 子集解析
# --------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_runtime_dir() -> Path:
    """默认运行期目录：<仓库根>/.runtime（TD §3）。"""
    return _repo_root() / RUNTIME_DIR_NAME


def default_inventory_path() -> Path:
    """项目默认远程 inventory：<仓库根>/inventory/hosts.ini。"""
    return _repo_root() / DEFAULT_INVENTORY_RELATIVE_PATH


def _parse_section_header(line: str, lineno: int, source: str) -> str:
    if not line.endswith("]"):
        raise InventoryError(
            f"{_MSG['parse']}: {source} 第 {lineno} 行段头缺少 ']': {line!r}"
        )
    name = line[1:-1].strip()
    if not name:
        raise InventoryError(
            f"{_MSG['parse']}: {source} 第 {lineno} 行段名为空: {line!r}"
        )
    return name


def _parse_host_line(
    content: str, lineno: int, source: str
) -> Tuple[str, Optional[str]]:
    """解析主机行 `主机名 [key=value ...]` → (主机名, ansible_host|None)。

    仅提取 ansible_host（展示用 IP）；其余 key=value（含 ansible_user /
    ansible_ssh_private_key_file / ansible_password 等认证变量）**不读入**
    内存（RK-R3-04：工具不读取凭据）。
    """
    tokens = content.split()
    if not tokens:
        raise InventoryError(
            f"{_MSG['parse']}: {source} 第 {lineno} 行主机行为空"
        )
    name = tokens[0]
    ansible_host: Optional[str] = None
    for tok in tokens[1:]:
        m = re.fullmatch(r"([A-Za-z0-9_]+)=(.+)", tok)
        if not m:
            raise InventoryError(
                f"{_MSG['parse']}: {source} 第 {lineno} 行变量语法非法: {tok!r}"
            )
        key, value = m.group(1), m.group(2)
        if key == "ansible_host":
            ansible_host = value
        # 其余键（含认证类）不读取
    return name, ansible_host


def parse_inventory(
    path: Path,
) -> Tuple[List[HostEntry], Dict[str, List[str]]]:
    """解析 inventory 严格 INI 子集 → (主机列表, 组→主机名映射)。

    - 主机列表：全文件出现的全部主机（去重，保首见顺序），HostEntry.ip =
      ansible_host（声明时）否则主机名；
    - 组映射：组名 → 该组直接成员（:children 组经递归展开后的全量成员；
      环检测 → 解析错误）；:vars 段跳过；
    - 任何格式错误 → InventoryError（exit_code=10）。
    """
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InventoryError(f"{_MSG['missing']}: {source}") from exc
    except (OSError, UnicodeError) as exc:
        raise InventoryError(f"{_MSG['unreadable']}: {source}（{exc}）") from exc

    seen: List[str] = []
    ip_by_name: Dict[str, str] = {}
    group_members: Dict[str, List[str]] = {}
    children_decls: List[Tuple[str, List[str]]] = []
    section: Optional[str] = None
    section_is_vars = False
    section_is_children = False

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise InventoryError(
                f"{_MSG['parse']}: {source} 第 {lineno} 行缩进使用制表符（子集不支持）"
            )
        if line.startswith("[") or line.endswith("]"):
            name = _parse_section_header(line, lineno, source)
            section = name
            section_is_vars = name.endswith(":vars")
            section_is_children = name.endswith(":children")
            if not section_is_vars and not section_is_children:
                if name not in group_members:
                    group_members[name] = []
            continue
        if section is None:
            raise InventoryError(
                f"{_MSG['parse']}: {source} 第 {lineno} 行在段外: {line!r}"
            )
        if section_is_vars:
            continue  # :vars 内容（可能含认证变量）整体跳过，不读取
        name, ansible_host = _parse_host_line(line, lineno, source)
        if section_is_children:
            children_decls.append((section[: -len(":children")], name))
            continue
        if name not in seen:
            seen.append(name)
        if ansible_host is not None:
            ip_by_name[name] = ansible_host
        group_members.setdefault(section, []).append(name)

    if not seen:
        raise InventoryError(f"{_MSG['empty']}: {source}")

    hosts = [
        HostEntry(name=name, ip=ip_by_name.get(name, name)) for name in seen
    ]
    groups = _expand_children(group_members, children_decls, source)
    return hosts, groups


def _expand_children(
    group_members: Dict[str, List[str]],
    children_decls: List[Tuple[str, str]],
    source: str,
) -> Dict[str, List[str]]:
    """展开 [组:children] 声明：组 → 全量成员主机名（递归，环检测）。

    结果 = 自身直接成员 ∪ 所有子组全量成员；仅由 :children 声明组成的
    组也物化（无直接成员，成员全来自子组）；子组不存在 → 解析错误。
    """
    groups: Dict[str, List[str]] = {g: list(m) for g, m in group_members.items()}
    # 仅由 :children 声明组成的组（无直接成员）也物化为空组，保证
    # 组→成员映射完整（--limit 按组名选择时同样可用）
    for parent, _ in children_decls:
        if parent not in groups:
            groups[parent] = []

    def resolve(group: str, stack: Tuple[str, ...]) -> List[str]:
        if group in stack:
            raise InventoryError(
                f"{_MSG['parse']}: {source} 组循环引用: {' -> '.join(stack + (group,))}"
            )
        out = list(groups.get(group, []))  # 自身直接成员
        for child in children_decls:
            if child[0] != group:
                continue
            child_group = child[1]
            if child_group not in groups:
                raise InventoryError(
                    f"{_MSG['parse']}: {source} 组 {group!r} 的 :children 子组不存在: "
                    f"{child_group!r}"
                )
            for m in resolve(child_group, stack + (group,)):
                if m not in out:
                    out.append(m)
        return out

    for group in list(groups):
        groups[group] = resolve(group, ())
    return groups


# --------------------------------------------------------------------------
# --limit / --all 选择（cli-contract §3，同 ansible 语义子集）
# --------------------------------------------------------------------------


def _split_patterns(limit: str) -> List[str]:
    """把 limit 模式按逗号拆分为子模式列表（ansible 以 `,` 分隔）。"""
    parts = [p.strip() for p in limit.split(",") if p.strip()]
    if not parts:
        raise InventoryError(f"{_MSG['limit_syntax']}: {limit!r}")
    for part in parts:
        if ":" in part:
            raise InventoryError(
                f"{_MSG['limit_syntax']}: 组合符 ':' 不在本版本子集内"
                f"（支持：主机名/组名/glob/逗号列表/all），得到 {part!r}"
            )
    return parts


def _pattern_matches(
    pattern: str, host: HostEntry, groups: Dict[str, List[str]]
) -> bool:
    if pattern == "all":
        return True
    if pattern == host.name:
        return True
    if pattern == host.ip:
        return True
    if fnmatch.fnmatchcase(host.name, pattern):
        return True
    if fnmatch.fnmatchcase(host.ip, pattern):
        return True
    for group, members in groups.items():
        if host.name in members and (
            pattern == group or fnmatch.fnmatchcase(group, pattern)
        ):
            return True
    return False


def select_hosts(
    hosts: List[HostEntry],
    groups: Dict[str, List[str]],
    limit: Optional[str] = None,
) -> List[HostEntry]:
    """按 limit 模式选择主机（cli-contract §3；limit=None/“all”→ 全部）。

    模式子集：主机名精确、IP 精确、组名精确、glob（主机名/IP/组名）、
    逗号分隔列表、`all`；组合符 `:`（如 `db*:!db-2`）不支持 → 执行
    失败（10）；无任何主机匹配 → 执行失败（10，绝不静默跳过）。
    """
    if limit is None or limit == "all":
        return list(hosts)
    patterns = _split_patterns(limit)
    selected: List[HostEntry] = []
    for host in hosts:
        if any(_pattern_matches(p, host, groups) for p in patterns):
            selected.append(host)
    if not selected:
        raise InventoryError(
            f"{_MSG['limit_nomatch']}: {limit!r}（inventory 共 {len(hosts)} 台）"
        )
    return selected


# --------------------------------------------------------------------------
# 临时 inventory 生成（-H / --local；TD §3 .runtime/）
# --------------------------------------------------------------------------


def write_temp_inventory(
    hosts: List[HostEntry],
    runtime_dir: Optional[Path] = None,
    *,
    local: bool = False,
) -> Path:
    """在 .runtime/（默认 <仓库根>/.runtime，可用 runtime_dir 注入）生成临时
    inventory（INI：`[all]` + 主机行；--local 加 `ansible_connection=local`）。

    文件名 `inventory-<uuid8>.ini`；返回文件路径（绝不包含任何凭据）。
    """
    runtime_dir = Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[all]"]
    for h in hosts:
        entry = h.name
        if local:
            entry += " ansible_connection=local"
        lines.append(entry)
    content = "\n".join(lines) + "\n"
    path = runtime_dir / f"inventory-{uuid.uuid4().hex[:8]}.ini"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except OSError as exc:
        raise InventoryError(
            f"临时 inventory 写入失败: {path}（{exc}）"
        ) from exc
    return path


# --------------------------------------------------------------------------
# 主机选择入口（消费 cli.build_host_selection 的输出形状）
# --------------------------------------------------------------------------


def resolve_host_selection(
    selection: Dict[str, Any],
    runtime_dir: Optional[Path] = None,
) -> HostSelection:
    """按 cli 主机选择语义（cli-contract §3）解析 → HostSelection。

    selection 形状（inspect/cli.py build_host_selection）：
      {"kind": "local"}
      {"kind": "hosts", "hosts": [ip, ...]}
      {"kind": "inventory", "inventory": PATH, "limit": "all"|PATTERN|None}

    - local：临时 inventory（localhost ansible_connection=local，TD §10.1）；
    - hosts：-H 列表 → 若存在默认 `inventory/hosts.ini`，在该文件上按
      主机组/主机名/IP 选择并交给 Ansible；否则生成无凭据临时 inventory
      （[all] + IP），保留旧的显式认证环境变量兼容路径；空列表 → 用法错误 2；
    - inventory：解析用户 inventory（不改写），limit=None/“all”→ 全部主机
      （裸 `-i` 按 ansible 缺省语义 = 全部主机，本版本决策，见任务报告）；
      limit=PATTERN → select_hosts；路径不存在 → 用法错误 2。
    """
    kind = selection.get("kind")
    if kind == "local":
        hosts = [HostEntry(name="localhost", ip="127.0.0.1")]
        inv = write_temp_inventory(hosts, runtime_dir, local=True)
        return HostSelection(kind="local", inventory_file=inv, hosts=hosts)
    if kind == "hosts":
        raw = selection.get("hosts") or []
        names = [str(h).strip() for h in raw if str(h).strip()]
        if not names:
            raise InventoryError(_MSG["hosts_empty"], exit_code=EXIT_USAGE)

        default_inv = default_inventory_path()
        if default_inv.is_file():
            all_hosts, groups = parse_inventory(default_inv)
            requested_limit = ",".join(names)
            hosts = select_hosts(all_hosts, groups, requested_limit)
            # Ansible --limit matches inventory host names, not necessarily
            # ansible_host address values.  Resolve IP/group input first and
            # pass the selected inventory aliases to Ansible.
            limit = ",".join(host.name for host in hosts)
            return HostSelection(
                kind="inventory",
                inventory_file=default_inv,
                hosts=hosts,
                limit=limit,
            )

        hosts = [HostEntry(name=n, ip=n) for n in names]
        inv = write_temp_inventory(hosts, runtime_dir, local=False)
        return HostSelection(kind="hosts", inventory_file=inv, hosts=hosts)
    if kind == "inventory":
        inv_path = Path(selection.get("inventory", ""))
        if not inv_path.is_file():
            raise InventoryError(
                f"{_MSG['missing']}: {inv_path}", exit_code=EXIT_USAGE
            )
        hosts, groups = parse_inventory(inv_path)
        limit = selection.get("limit")  # "all"|PATTERN|None
        if limit is not None and limit != "all":
            hosts = select_hosts(hosts, groups, limit)
        return HostSelection(
            kind="inventory", inventory_file=inv_path, hosts=hosts, limit=limit
        )
    raise InventoryError(
        f"未知主机选择 kind: {kind!r}（期望 local/hosts/inventory）"
    )


__all__ = [
    "EXIT_EXEC",
    "EXIT_USAGE",
    "HostEntry",
    "HostSelection",
    "InventoryError",
    "RUNTIME_DIR_NAME",
    "DEFAULT_INVENTORY_RELATIVE_PATH",
    "default_runtime_dir",
    "default_inventory_path",
    "parse_inventory",
    "resolve_host_selection",
    "select_hosts",
    "write_temp_inventory",
]
