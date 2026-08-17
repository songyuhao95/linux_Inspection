"""tests/test_inventory.py — 主机选择与 inventory 解析（T-103）测试。

覆盖（对应合同 AC-6 文本 marker 与冻结 DAG 语义）：
  1. 严格 INI 子集解析：段/组/:vars 跳过/:children 级联（环检测）/
     ansible_host 提取/行内语法错误/空 inventory（exit_code=10）；
  2. 凭据不读取（RK-R3-04）：ansible_user/ansible_password/
     ansible_ssh_private_key_file 等认证变量不进入任何结果对象；
  3. --limit/--all 选择：全部/精确（主机名/IP/组名）/glob/逗号列表/
     无匹配（10）/不支持组合符 `:`（10）；
  4. -H 临时 inventory 生成（.runtime/，可注入 runtime_dir）：内容
     含 [all]+主机行，不含凭据；空列表 → 用法错误 2；
  5. --local：localhost ansible_connection=local；
  6. -i 解析：路径缺失 → 用法错误 2；用户 inventory 文件不改写；
     limit=None/“all” → 全部主机（裸 -i = 全部，本版本决策）。

inventory.py 不发起任何连接、不读取凭据、不执行命令（TD §4）。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _ROOT / "tests" / "fixtures" / "inventory"

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


inv = _load_module("t103_inventory", _ROOT / "inspect" / "inventory.py")


# ==========================================================================
# 1. 严格 INI 子集解析
# ==========================================================================


def test_parse_inventory_groups_and_hosts():
    hosts, groups = inv.parse_inventory(_FIXTURES / "hosts.yml")
    assert [h.name for h in hosts] == ["db-1", "db-2", "web-1", "web-2", "cache-1"]
    assert [h.ip for h in hosts] == [
        "10.0.1.11", "10.0.1.12", "10.0.1.21", "10.0.1.22", "10.0.2.31",
    ]
    assert sorted(groups["db"]) == ["db-1", "db-2"]
    assert groups["web"] == ["web-1", "web-2"]
    assert groups["cache"] == ["cache-1"]


def test_parse_inventory_vars_section_skipped():
    """[all:vars] 段内容（含认证变量）整体跳过，不产生主机也不进入结果。"""
    hosts, _ = inv.parse_inventory(_FIXTURES / "hosts.yml")
    names = [h.name for h in hosts]
    assert "ansible_user" not in names
    assert "root" not in names
    assert len(hosts) == 5


def test_parse_inventory_credentials_never_extracted():
    """认证变量不进入任何结果对象（RK-R3-04）：HostEntry 仅 name/ip。"""
    hosts, _ = inv.parse_inventory(_FIXTURES / "hosts.yml")
    for h in hosts:
        assert h.to_dict() == {"name": h.name, "ip": h.ip}
        assert not any(
            k in h.to_dict()
            for k in ("ansible_user", "ansible_password", "ansible_ssh_private_key_file")
        )
    # 字符串级核对：解析结果文本中不出现任何认证变量名
    blob = repr([h.to_dict() for h in hosts])
    for secret_key in ("ansible_user", "ansible_password", "ansible_ssh_private_key_file"):
        assert secret_key not in blob


def test_parse_inventory_children_expansion():
    hosts, groups = inv.parse_inventory(_FIXTURES / "hosts_groups_children.ini")
    assert sorted(groups["allprod"]) == ["db-1", "db-2", "web-1"]
    assert sorted(groups["big"]) == ["cache-1", "db-1", "db-2", "web-1"]
    # :children 声明不产生主机
    assert len(hosts) == 4


def test_parse_inventory_children_cycle_detected(tmp_path):
    f = tmp_path / "cycle.ini"
    f.write_text(
        "[a:children]\nb\n[b:children]\na\n[a]\nx\n",
        encoding="utf-8",
    )
    with pytest.raises(inv.InventoryError, match="循环引用") as ei:
        inv.parse_inventory(f)
    assert ei.value.exit_code == 10


def test_parse_inventory_children_unknown_group(tmp_path):
    f = tmp_path / "unknown.ini"
    f.write_text("[a:children]\nnope\n[a]\nx\n", encoding="utf-8")
    with pytest.raises(inv.InventoryError, match="子组不存在"):
        inv.parse_inventory(f)


def test_parse_inventory_bad_syntax():
    with pytest.raises(inv.InventoryError, match="解析失败") as ei:
        inv.parse_inventory(_FIXTURES / "bad_inventory.ini")
    assert ei.value.exit_code == 10


def test_parse_inventory_empty_inventory():
    with pytest.raises(inv.InventoryError, match="无任何主机") as ei:
        inv.parse_inventory(_FIXTURES / "empty_inventory.ini")
    assert ei.value.exit_code == 10


def test_parse_inventory_missing_file(tmp_path):
    with pytest.raises(inv.InventoryError, match="不存在"):
        inv.parse_inventory(tmp_path / "nope.ini")


def test_parse_inventory_missing_bracket(tmp_path):
    f = tmp_path / "bad.ini"
    f.write_text("[db\nx\n", encoding="utf-8")
    with pytest.raises(inv.InventoryError, match="缺少"):
        inv.parse_inventory(f)


def test_parse_inventory_bad_var_syntax(tmp_path):
    f = tmp_path / "bad.ini"
    f.write_text("[db]\nx badvar\n", encoding="utf-8")
    with pytest.raises(inv.InventoryError, match="变量语法非法"):
        inv.parse_inventory(f)


def test_parse_inventory_content_outside_section(tmp_path):
    f = tmp_path / "bad.ini"
    f.write_text("x\n[db]\ny\n", encoding="utf-8")
    with pytest.raises(inv.InventoryError, match="段外"):
        inv.parse_inventory(f)


def test_parse_inventory_duplicate_hosts_deduplicated(tmp_path):
    f = tmp_path / "dup.ini"
    f.write_text("[a]\nx\n[b]\nx\n", encoding="utf-8")
    hosts, groups = inv.parse_inventory(f)
    assert [h.name for h in hosts] == ["x"]
    assert groups == {"a": ["x"], "b": ["x"]}


def test_parse_inventory_comments_and_blank_lines(tmp_path):
    f = tmp_path / "c.ini"
    f.write_text(
        "# 非实测数据（fixture）：注释行\n\n[a]\n# 段内注释\nx ansible_host=1.2.3.4\n",
        encoding="utf-8",
    )
    hosts, _ = inv.parse_inventory(f)
    assert hosts[0].name == "x" and hosts[0].ip == "1.2.3.4"


# ==========================================================================
# 2. --limit / --all 选择（cli-contract §3）
# ==========================================================================


@pytest.fixture()
def parsed():
    hosts, groups = inv.parse_inventory(_FIXTURES / "hosts.yml")
    return hosts, groups


def test_select_all_when_none_or_all(parsed):
    hosts, _ = parsed
    assert [h.name for h in inv.select_hosts(hosts, {}, None)] == [
        h.name for h in hosts
    ]
    assert [h.name for h in inv.select_hosts(hosts, {}, "all")] == [
        h.name for h in hosts
    ]


def test_select_exact_hostname_and_ip(parsed):
    hosts, groups = parsed
    assert [h.name for h in inv.select_hosts(hosts, groups, "db-1")] == ["db-1"]
    assert [h.name for h in inv.select_hosts(hosts, groups, "10.0.1.12")] == ["db-2"]


def test_select_group(parsed):
    hosts, groups = parsed
    assert sorted(h.name for h in inv.select_hosts(hosts, groups, "web")) == [
        "web-1",
        "web-2",
    ]


def test_select_glob(parsed):
    hosts, groups = parsed
    assert sorted(h.name for h in inv.select_hosts(hosts, groups, "db-*")) == [
        "db-1",
        "db-2",
    ]
    assert [h.name for h in inv.select_hosts(hosts, groups, "10.0.2.*")] == ["cache-1"]


def test_select_comma_list(parsed):
    hosts, groups = parsed
    assert [h.name for h in inv.select_hosts(hosts, groups, "db-1, cache-1")] == [
        "db-1",
        "cache-1",
    ]


def test_select_no_match_raises(parsed):
    hosts, groups = parsed
    with pytest.raises(inv.InventoryError, match="未匹配任何主机") as ei:
        inv.select_hosts(hosts, groups, "nope-*")
    assert ei.value.exit_code == 10


def test_select_unsupported_combinator_raises(parsed):
    hosts, groups = parsed
    with pytest.raises(inv.InventoryError, match="组合符") as ei:
        inv.select_hosts(hosts, groups, "db*:!db-2")
    assert ei.value.exit_code == 10


def test_select_empty_pattern_raises(parsed):
    hosts, groups = parsed
    with pytest.raises(inv.InventoryError, match="语法"):
        inv.select_hosts(hosts, groups, ",")


# ==========================================================================
# 3. 临时 inventory 生成（-H / --local；.runtime/）
# ==========================================================================


def test_write_temp_inventory_content(tmp_path):
    path = inv.write_temp_inventory(
        [inv.HostEntry("10.0.0.1", "10.0.0.1"), inv.HostEntry("10.0.0.2", "10.0.0.2")],
        runtime_dir=tmp_path,
    )
    assert path.parent == tmp_path
    assert path.name.startswith("inventory-") and path.name.endswith(".ini")
    assert path.read_text(encoding="utf-8") == "[all]\n10.0.0.1\n10.0.0.2\n"


def test_write_temp_inventory_local_connection(tmp_path):
    path = inv.write_temp_inventory(
        [inv.HostEntry("localhost", "127.0.0.1")], runtime_dir=tmp_path, local=True
    )
    assert path.read_text(encoding="utf-8") == (
        "[all]\nlocalhost ansible_connection=local\n"
    )


def test_write_temp_inventory_no_credentials(tmp_path):
    path = inv.write_temp_inventory(
        [inv.HostEntry("h", "1.2.3.4")], runtime_dir=tmp_path
    )
    content = path.read_text(encoding="utf-8")
    assert "ansible_user" not in content and "password" not in content


def test_resolve_hosts_selection(tmp_path):
    sel = inv.resolve_host_selection(
        {"kind": "hosts", "hosts": ["10.0.0.1", "10.0.0.2"]}, runtime_dir=tmp_path
    )
    assert sel.kind == "hosts"
    assert [h.name for h in sel.hosts] == ["10.0.0.1", "10.0.0.2"]
    assert sel.inventory_file.parent == tmp_path


def test_resolve_hosts_selection_empty_usage_error(tmp_path):
    with pytest.raises(inv.InventoryError) as ei:
        inv.resolve_host_selection({"kind": "hosts", "hosts": []}, runtime_dir=tmp_path)
    assert ei.value.exit_code == inv.EXIT_USAGE  # 2


def test_resolve_local_selection(tmp_path):
    sel = inv.resolve_host_selection({"kind": "local"}, runtime_dir=tmp_path)
    assert sel.kind == "local"
    assert [h.name for h in sel.hosts] == ["localhost"]
    assert sel.inventory_file.read_text(encoding="utf-8").endswith(
        "localhost ansible_connection=local\n"
    )


def test_resolve_inventory_selection_all(tmp_path):
    sel = inv.resolve_host_selection(
        {"kind": "inventory", "inventory": str(_FIXTURES / "hosts.yml"), "limit": "all"},
        runtime_dir=tmp_path,
    )
    assert sel.kind == "inventory"
    assert sel.limit == "all"
    assert len(sel.hosts) == 5
    assert sel.inventory_file == _FIXTURES / "hosts.yml"  # 用户文件不改写


def test_resolve_inventory_selection_bare_i_is_all(tmp_path):
    """裸 -i（limit=None）按 ansible 缺省语义 = 全部主机（本版本决策，见任务报告）。"""
    sel = inv.resolve_host_selection(
        {"kind": "inventory", "inventory": str(_FIXTURES / "hosts.yml"), "limit": None},
        runtime_dir=tmp_path,
    )
    assert len(sel.hosts) == 5


def test_resolve_inventory_selection_limit(tmp_path):
    sel = inv.resolve_host_selection(
        {"kind": "inventory", "inventory": str(_FIXTURES / "hosts.yml"), "limit": "db"},
        runtime_dir=tmp_path,
    )
    assert [h.name for h in sel.hosts] == ["db-1", "db-2"]


def test_resolve_inventory_selection_missing_usage_error(tmp_path):
    with pytest.raises(inv.InventoryError) as ei:
        inv.resolve_host_selection(
            {"kind": "inventory", "inventory": str(tmp_path / "nope.ini"), "limit": None},
            runtime_dir=tmp_path,
        )
    assert ei.value.exit_code == inv.EXIT_USAGE  # 2


def test_resolve_unknown_kind_raises(tmp_path):
    with pytest.raises(inv.InventoryError, match="未知主机选择"):
        inv.resolve_host_selection({"kind": "wat"}, runtime_dir=tmp_path)


# ==========================================================================
# 4. 合同 AC-6 文本 marker 镜像
# ==========================================================================


def test_ac6_limit_hosts_markers():
    src = (_ROOT / "inspect" / "inventory.py").read_text(encoding="utf-8")
    assert "limit" in src
    assert "hosts" in src
