"""tests/test_render_html.py — T-127 离线单文件 HTML 渲染测试（合同 AC-1）。

覆盖（合同必需步骤 4 + mitigations + DAG §10 AC 对应项，REQ-R-05/06/07/08）：
  - 单文件零外链：模板与最终产物均无 `<link`/`<script src`/`src=`/
    `fetch(`/`http(s):`/`url(`（REQ-R-05；AC-2 的模板级机械断言由合同
    命令执行，本文件对模板与产物两层都断言）；
  - 内嵌 JSON 与事实源一致（REQ-R-05/AC-2：内嵌 JSON 只读展示）；
  - 内嵌 JSON 不可越界：`</script` 被转义为 `<\\/script`，注入载荷留在
    JSON 块内（REQ-R-05 安全项 + 合同 mitigation"JSON 内嵌只读"）；
  - 不可信文本 HTML 转义：evidence/error.message/provenance 中的
    `<script>` 注入在正文呈 `&lt;script&gt;`（合同 mitigation"不可信文本
    HTML 转义"，测试断言 `<script>` 注入被转义）；
  - 布局：左导航（主机/状态/中间件多选筛选）+ 右滚动区（Run 摘要置顶）
    （宏观卡片 → 主机详情逐指标卡片 raw/normalized/unit/status/
    threshold/evidence/error/provenance）（REQ-R-06）；
  - 四状态色板/徽标：#2E7D32/#F9A825/#C62828/#757575；execution_status
    描边徽标区分于业务状态填充徽标（REQ-R-07）；
  - 交互：状态/主机/中间件多选、搜索和三种分组视图接线（data-* 属性 + addEventListener）；
    展示层零业务计算（JS 无 reduce/parseInt/Number）——宏观计数为
    渲染期静态文本（REQ-R-06 + mitigation"展示层不二次计算"）；
  - 打印友好：@media print 默认只打印宏观摘要，print-details 开关
    展开主机详情（REQ-R-06）；
  - 文件名 `<inspection-id>.html` 与 out_path 覆盖（TD §3 / cli-contract
    §2 `--html PATH` 函数参数语义）；
  - 宏观卡片计数与 execution_summary 一致、UNKNOWN 可见（REQ-R-08 渲染
    期一致性 + RR §6.2）；
  - 渲染失败：空输入/混合 inspection_id/模板缺失/输入损坏 →
    RenderHtmlError(exit_code=10)（cli-contract §4）。

只读使用 tests/fixtures/json/ 与 tests/fixtures/html/；不连接、不执行命令。
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from inspect import render_html as rh

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "html"
TEMPLATE = (
    Path(__file__).parent.parent / "inspect" / "templates" / "html-report-v1.html"
)

# RR §5 四状态色板（测试机械断言原文大小写）
PALETTE = {
    "OK": "#2E7D32",
    "WARN": "#F9A825",
    "CRIT": "#C62828",
    "UNKNOWN": "#757575",
}
INSPECTION_ID = "insp-20260814120000-node-fx01"
RUN_ID = "run-20260814-001"

DATA_RE = re.compile(
    r'<script type="application/json" id="inspection-data">(.*?)</script>',
    re.S,
)
PLACEHOLDER_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


# --------------------------------------------------------------------------
# 夹具与渲染辅助
# --------------------------------------------------------------------------


def fixture_docs(name: str = "multi-host.json") -> list:
    """每次从文件重新加载（测试内修改不跨用例污染）。"""
    return json.loads((FIXTURE_HTML / name).read_text(encoding="utf-8"))


def render(docs, out_path) -> Path:
    return rh.render_html(docs, out_path=out_path)


def render_str(docs, tmp_path, name: str = "report.html") -> str:
    return Path(render(docs, tmp_path / name)).read_text(encoding="utf-8")


def embedded_blob(html_text: str) -> str:
    """内嵌 JSON 脚本块原始文本。"""
    m = DATA_RE.search(html_text)
    assert m, "内嵌 JSON 脚本块缺失"
    return m.group(1)


def embedded_json(html_text: str) -> list:
    return json.loads(embedded_blob(html_text))


def body_text(html_text: str) -> str:
    """去掉内嵌 JSON 块后的正文（转义断言作用域：JSON 块为结构化数据）。"""
    return DATA_RE.sub("", html_text)


def inline_js(html_text: str) -> str:
    """过滤脚本（非 JSON 内嵌块）文本。"""
    m = re.search(r"<script>(.*?)</script>", html_text, re.S)
    assert m, "内联 JS 脚本块缺失"
    return m.group(1)


def script_tags(html_text: str) -> list:
    return re.findall(r"<script[^>]*>", html_text)


# --------------------------------------------------------------------------
# 1. 单文件零外链（REQ-R-05 / AC-2 模板级断言）
# --------------------------------------------------------------------------


class TestSingleFile:
    """AC-2 模板级机械断言 + 最终产物双层零外链。"""

    FORBIDDEN = ["<link", "<script src", "src=", "fetch(", "http:", "https:", "url("]

    def test_template_has_no_external_resources(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        for bad in self.FORBIDDEN:
            assert bad not in s, "模板出现外链资源标记: %r" % bad

    def test_rendered_html_has_no_external_resources(self, tmp_path):
        s = render_str(fixture_docs(), tmp_path)
        body = body_text(s)
        for bad in self.FORBIDDEN:
            assert bad not in body, "产物正文出现外链资源标记: %r" % bad

    def test_rendered_script_tags_are_expected_two(self, tmp_path):
        """产物仅两个 script 标签：内嵌 JSON + 内联过滤脚本（均无 src）。"""
        s = render_str(fixture_docs(), tmp_path)
        tags = script_tags(s)
        assert len(tags) == 2, tags
        assert all("src" not in t for t in tags)

    def test_ac2_template_assertion_verbatim(self):
        """合同 AC-2 命令原样通过。"""
        s = TEMPLATE.read_text(encoding="utf-8")
        assert "<link" not in s
        assert "<script src" not in s


# --------------------------------------------------------------------------
# 2. 内嵌 JSON（REQ-R-05：与事实源一致、只读、不可越界）
# --------------------------------------------------------------------------


class TestEmbeddedJson:
    def test_embedded_json_matches_source(self, tmp_path):
        docs = fixture_docs()
        assert embedded_json(render_str(docs, tmp_path)) == docs

    def test_embedded_json_is_readonly_display_data(self, tmp_path):
        """内嵌 JSON 与事实源逐字节一致（展示层只读，不二次计算改写）。"""
        docs = fixture_docs()
        blob = embedded_blob(render_str(docs, tmp_path))
        assert json.loads(blob) == docs
        # 内嵌块不参与模板替换：数据中不应出现占位符形态
        assert PLACEHOLDER_RE.search(blob) is None

    def test_script_tag_breakout_escaped(self, tmp_path):
        """`</script>` 注入被转义为 `<\\/script`，载荷留在 JSON 块内。"""
        docs = fixture_docs()
        docs[0]["metrics"][0]["evidence"]["output_summary"] = (
            "</script><script>alert(1)</script>"
        )
        s = render_str(docs, tmp_path)
        blob = embedded_blob(s)
        assert "</script>" not in blob
        assert "<\\/script>" in blob
        # 转义后仍是合法 JSON，且与事实源一致（浏览器解析 `\/` 后原样）
        assert json.loads(blob) == docs

    def test_embedded_json_keeps_dollar_signs(self, tmp_path):
        """数据内合法 "$" 原样保留（string.Template 映射值原样插入）。"""
        docs = fixture_docs()
        docs[1]["metrics"][0]["evidence"]["command"] = "sh -c 'echo $HOME'"
        docs[1]["metrics"][0]["provenance"]["notes"] = "cost $10.5"
        blob = embedded_blob(render_str(docs, tmp_path))
        assert "$HOME" in blob
        assert "$10.5" in blob
        assert "$$" not in blob

    def test_dollar_in_body_preserved(self, tmp_path):
        """正文中的 "$" 原样显示（不经模板误解析，也不被转义破坏）。"""
        docs = fixture_docs()
        docs[2]["metrics"][0]["evidence"]["output_summary"] = "cmd $VAR ok"
        body = body_text(render_str(docs, tmp_path))
        assert "$VAR" in body
        assert "$$" not in body


# --------------------------------------------------------------------------
# 3. 不可信文本 HTML 转义（合同 mitigation；测试断言 <script> 注入被转义）
# --------------------------------------------------------------------------


class TestEscaping:
    def test_script_injection_escaped_everywhere(self, tmp_path):
        """evidence/error.message/provenance 三处注入均转义为实体。"""
        payload = "<script>alert(1)</script>"
        docs = fixture_docs()
        docs[0]["metrics"][0]["evidence"]["output_summary"] = payload
        docs[1]["metrics"][3]["error"] = {
            "code": "PERMISSION_DENIED",
            "message": payload,
            "metric_status": "UNKNOWN",
        }
        docs[2]["metrics"][0]["provenance"]["notes"] = payload
        body = body_text(render_str(docs, tmp_path))
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert body.count("&lt;script&gt;") >= 3
        assert "alert(1)" in body  # 载荷文本保留（转义而非丢弃）

    def test_html_special_chars_escaped(self, tmp_path):
        docs = fixture_docs()
        docs[0]["metrics"][1]["evidence"]["output_summary"] = (
            'echo "a & b < c > d" and \'q\''
        )
        body = body_text(render_str(docs, tmp_path))
        assert "a &amp; b &lt; c &gt; d" in body
        assert '"a & b < c > d"' not in body
        assert "'q'" not in body
        assert "&lt; c" in body  # "< c"（原样含空格）转义为 "&lt; c"

    def test_fixture_special_chars_escaped(self, tmp_path):
        """夹具固有特殊字符（a < b & c）在产物中为实体。"""
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert "a &lt; b &amp; c" in body
        assert "a < b & c" not in body

    def test_attribute_injection_escaped(self, tmp_path):
        """属性值注入（引号逃逸）被转义：data-*/id 不可注入事件处理器。"""
        docs = fixture_docs()
        docs[0]["host"]["name"] = 'x" onclick="alert(1)'
        body = body_text(render_str(docs, tmp_path))
        assert "onclick=" + '"alert' not in body
        assert "&quot;" in body

    def test_error_message_escaped_in_card(self, tmp_path):
        docs = fixture_docs()
        docs[1]["metrics"][3]["error"]["message"] = (
            "cannot read <log> & 'secret'"
        )
        body = body_text(render_str(docs, tmp_path))
        # 引号（含单引号）同样转义（quote=True，属性值安全）
        assert "cannot read &lt;log&gt; &amp; &#x27;secret&#x27;" in body
        assert "cannot read <log> & 'secret'" not in body

    def test_esc_unit(self):
        assert rh.esc("a<b>&\"'") == "a&lt;b&gt;&amp;&quot;&#x27;"
        assert rh.esc(None) == ""
        assert rh.esc(0) == "0"
        assert rh.esc(False) == "False"


# --------------------------------------------------------------------------
# 4. 布局：左导航 + 右滚动区（REQ-R-06）
# --------------------------------------------------------------------------


class TestLayout:
    def test_nav_sections_present(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        for section in ("Run 摘要", "主机列表", "状态筛选", "中间件"):
            assert section in body, "报表缺少: %s" % section
        assert body.index('<header class="run-header"') > body.index('<main class="content">')
        assert "指标维度" not in body

    def test_left_nav_before_content(self, tmp_path):
        s = render_str(fixture_docs(), tmp_path)
        assert s.index('<nav class="nav"') < s.index('<main class="content"')

    def test_macro_cards_before_host_details(self, tmp_path):
        s = render_str(fixture_docs(), tmp_path)
        assert s.index('class="macro-cards"') < s.index('class="host-detail"')

    def test_run_summary_fields(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert RUN_ID in body
        assert INSPECTION_ID in body
        assert "OK / WARN / CRIT / UNKNOWN" in body
        assert "8 / 1 / 1 / 2" in body  # run 级四状态合计
        assert "技术失败（failed）" in body
        assert "执行状态分布" in body

    def test_run_header_totals(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert "主机 3" in body
        assert "8 / 1 / 1 / 2" in body
        assert "技术失败 1" in body

    def test_metric_card_fields_complete(self, tmp_path):
        """逐指标卡片含 raw/normalized/unit/status/threshold/evidence/
        error/provenance 全集（RR §4）。"""
        body = body_text(render_str(fixture_docs(), tmp_path))
        for label in (
            "raw_value", "normalized_value", "unit",
            "阈值 rule_id", "阈值 value", "阈值 source_anchor", "阈值 notes",
            "证据 command", "证据 output_summary", "证据 raw_ref", "证据 sampled_at",
            "错误 code", "错误 message",
            "来源 config_sources", "来源 doc_sources", "来源 notes",
        ):
            assert label in body, "指标卡片缺少字段: %s" % label
        # 阈值层字段（RR §4 threshold）与实测值
        assert "阈值 layer" in body
        assert "linux-common-p0-v1.memory.available_percent.crit" in body
        assert "PERMISSION_DENIED" in body
        assert "cannot read /opt/redis/logs/redis.log" in body

    def test_cards_carry_filter_attributes(self, tmp_path):
        s = render_str(fixture_docs(), tmp_path)
        # 仅指标卡开标签（导航按钮/宏观卡/主机区也带 data-*，需限定作用域）
        openings = re.findall(r'<div class="metric-card[^"]*"[^>]*>', s)
        assert len(openings) == 36  # 三种静态分组视图 × 3 主机 × 4 指标
        statuses = re.findall(r'data-status="(OK|WARN|CRIT|UNKNOWN)"', "".join(openings))
        assert len(statuses) == 36
        hosts = re.findall(r'data-host="node-fx0[1-3]"', "".join(openings))
        assert len(hosts) == 36
        metrics = re.findall(r'data-metric-id="local\.[^"]+"', "".join(openings))
        assert len(metrics) == 36
        middleware = re.findall(r'data-middleware="([^"]+)"', "".join(openings))
        assert set(middleware) >= {"elasticsearch", "redis", "mysql"}
        for st in ("OK", "WARN", "CRIT", "UNKNOWN"):
            assert st in statuses  # 四状态均出现（UNKNOWN 可见，RR §6.2）

    def test_host_section_ids(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        for host in ("node-fx01", "node-fx02", "node-fx03"):
            assert 'id="host-' + host + '"' in body


# --------------------------------------------------------------------------
# 5. 四状态色板与徽标（REQ-R-07 / RR §5）
# --------------------------------------------------------------------------


class TestPaletteAndBadges:
    def test_palette_hex_in_template(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        for st, hexv in PALETTE.items():
            assert hexv in s, "色板缺失 %s %s" % (st, hexv)

    def test_palette_hex_in_rendered(self, tmp_path):
        s = render_str(fixture_docs(), tmp_path)
        for hexv in PALETTE.values():
            assert hexv in s

    def test_css_vars_bound_to_palette(self):
        """CSS 变量与 RR §5 色板一一绑定（色板常量为唯一真源）。"""
        s = TEMPLATE.read_text(encoding="utf-8")
        for st, hexv in PALETTE.items():
            assert "--status-" + st.lower() + ": " + hexv in s

    def test_status_chips_use_fill_colors(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        assert ".chip-ok      { background: #2E7D32; }" in s
        assert ".chip-crit    { background: #C62828; }" in s
        assert ".chip-unknown { background: #757575; }" in s

    def test_execution_badges_distinct_outline(self):
        """execution_status 徽标为描边样式（区别于业务状态填充徽标，RR §5）。"""
        s = TEMPLATE.read_text(encoding="utf-8")
        assert "border: 2px solid" in s  # 描边徽标
        assert ".exec-success" in s and ".exec-partial" in s and ".exec-error" in s
        # PARTIAL 灰黄边框（RR §5 示例）
        assert ".exec-partial" in s and "#FFF8E1" in s

    def test_rendered_badges(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert 'exec-badge exec-success">SUCCESS' in body
        assert 'exec-badge exec-partial">PARTIAL' in body
        # 夹具无 ERROR 主机（CSS 选择器文本允许出现，徽标类不允许）
        assert 'exec-badge exec-error"' not in body

    def test_status_filter_options_and_colors(self, tmp_path):
        s = TEMPLATE.read_text(encoding="utf-8")
        body = body_text(render_str(fixture_docs(), tmp_path))
        for st, hexv in PALETTE.items():
            assert 'data-filter-kind="status" data-filter-value="' + st + '"' in body
            assert hexv in s


# --------------------------------------------------------------------------
# 6. 过滤交互（状态/主机/中间件 + 分组；展示层不二次计算）
# --------------------------------------------------------------------------


class TestFilterInteraction:
    def test_multi_select_filters(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert body.count('class="multi-select"') == 3
        for kind in ("host", "status", "middleware"):
            assert 'data-filter-kind="' + kind + '"' in body
            assert 'class="filter-search" data-search-kind="' + kind + '"' in body
            assert 'class="filter-check"' in body
        for host in ("node-fx01", "node-fx02", "node-fx03"):
            assert 'data-filter-kind="host" data-filter-value="' + host + '"' in body
        for middleware in ("elasticsearch", "redis", "mysql"):
            assert 'data-filter-kind="middleware" data-filter-value="' + middleware + '"' in body

    def test_group_modes_present(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        for value, label in (("host", "按主机分组"), ("status", "按状态分组"), ("middleware", "按中间件分组")):
            assert 'option value="' + value + '"' in body
            assert label in body
            assert 'data-group-mode="' + value + '"' in body

    def test_js_wires_filters_and_grouping(self, tmp_path):
        js = inline_js(render_str(fixture_docs(), tmp_path))
        for needle in (
            "addEventListener", "data-filter-kind", "data-filter-value", "data-middleware",
            "classList", "applyFilters", "filter-reset", "filter-search", "group-by-select",
            "group-view", "hidden",
        ):
            assert needle in js, "JS 缺少交互接线: %s" % needle

    def test_js_card_click_expands_evidence(self, tmp_path):
        js = inline_js(render_str(fixture_docs(), tmp_path))
        assert "card-details" in js
        assert "bindCardToggle" in js
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert body.count('details class="card-details"') == 36

    def test_reset_button_present(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert 'id="filter-reset"' in body
        assert "清除筛选" in body

    def test_js_no_business_computation(self, tmp_path):
        """展示层不二次计算：JS 不出现计数/数值解析/聚合 API。"""
        js = inline_js(render_str(fixture_docs(), tmp_path))
        for forbidden in ("reduce(", "parseInt", "parseFloat", "Number(", "Math."):
            assert forbidden not in js, "JS 出现业务计算 API: %s" % forbidden

    def test_counts_are_server_rendered_text(self, tmp_path):
        """宏观计数为渲染期静态文本（非 JS 计算），与执行摘要一致。"""
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert 'count-ok">OK<b>8</b>' not in body
        assert 'count-ok">OK<b>2</b>' in body
        assert 'count-crit">CRIT<b>1</b>' in body
        assert 'count-unknown">UNKNOWN<b>2</b>' in body


# --------------------------------------------------------------------------
# 7. 打印友好（REQ-R-06：默认宏观摘要，详情可展开）
# --------------------------------------------------------------------------


class TestPrintFriendly:
    def test_print_media_rule_exists(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        assert "@media print" in s

    def test_print_default_hides_details(self):
        """默认打印：主机详情与卡内证据折叠，仅宏观摘要。"""
        s = TEMPLATE.read_text(encoding="utf-8")
        assert ".host-detail, .group-view:not(.active), .card-details { display: none; }" in s

    def test_print_toggle_expands_details(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        assert "body.print-details .host-detail, body.print-details .group-view.active { display: block; }" in s
        assert "body.print-details .card-details { display: block; }" in s

    def test_print_hides_nav_and_toolbar(self):
        s = TEMPLATE.read_text(encoding="utf-8")
        print_block = s[s.index("@media print"):]
        assert ".nav, .toolbar { display: none; }" in print_block

    def test_print_toggle_control_present(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert 'id="print-details-toggle"' in body
        assert "打印时包含主机详情" in body
        js = inline_js(render_str(fixture_docs(), tmp_path))
        assert "print-details" in js


# --------------------------------------------------------------------------
# 8. 文件名（TD §3 / cli-contract §2 --html PATH 函数参数语义）
# --------------------------------------------------------------------------


class _FixedNow:
    """固定"生成时间"，使跨用例渲染字节级可复现。"""

    @staticmethod
    def now():
        return datetime(2026, 8, 15, 12, 0, 0).astimezone()


class TestFileName:
    def test_default_filename_is_inspection_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = render(fixture_docs(), out_path=None)
        # 缺省文件名 `<inspection-id>.html`，相对当前目录（TD §3）
        assert out.name == INSPECTION_ID + ".html"
        assert out.parent == Path(".")
        assert (tmp_path / out.name).is_file()

    def test_out_path_overrides_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = render(fixture_docs(), out_path=tmp_path / "custom.html")
        assert out == tmp_path / "custom.html"
        assert out.is_file()
        assert not (tmp_path / (INSPECTION_ID + ".html")).exists()

    def test_out_path_nested_directory_created(self, tmp_path):
        out = render(fixture_docs(), out_path=tmp_path / "sub" / "dir" / "r.html")
        assert out.is_file()

    def test_rendered_content_identical_across_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rh, "datetime", _FixedNow)
        a = render_str(fixture_docs(), tmp_path, name="a.html")
        b = render_str(fixture_docs(), tmp_path, name="b.html")
        assert a == b


# --------------------------------------------------------------------------
# 9. 宏观卡片与一致性（REQ-R-08 / RR §6）
# --------------------------------------------------------------------------


class TestMacroCards:
    def test_macro_counts_match_execution_summary(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        # node-fx01: ok=2 warn=1 crit=1 unknown=0
        assert 'count-ok">OK<b>2</b>' in body
        assert 'count-warn">WARN<b>1</b>' in body
        assert 'count-crit">CRIT<b>1</b>' in body
        assert 'count-unknown">UNKNOWN<b>0</b>' in body
        # node-fx02: ok=2 unknown=2
        assert 'count-unknown">UNKNOWN<b>2</b>' in body
        # node-fx03: ok=4
        assert 'count-ok">OK<b>4</b>' in body

    def test_execution_badge_and_failure_in_macro(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        # node-fx02 PARTIAL：技术失败可见（RR §6.2 / HR §8）
        fx02 = body[body.index('data-host="node-fx02"'):]
        assert "exec-partial" in fx02
        assert "技术失败 1" in fx02
        assert "执行状态：PARTIAL" in fx02  # 宏观卡 meta 行

    def test_conclusions(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert "存在 CRIT 告警 1 项，请尽快处理" in body
        assert "执行状态 PARTIAL，存在技术失败 1 项" in body
        assert "全部指标正常" in body  # node-fx03

    def test_unknown_visible_in_macro_and_cards(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert 'count-unknown">UNKNOWN<b>2</b>' in body
        openings = re.findall(r'<div class="metric-card[^"]*"[^>]*>', body)
        unknown_cards = [o for o in openings if 'data-status="UNKNOWN"' in o]
        assert len(unknown_cards) == 6  # 三种视图各包含 2 个 UNKNOWN 指标卡

    def test_run_conclusion(self, tmp_path):
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert "主机 3" in body
        assert "CRIT 指标 1 项" in body
        assert "技术失败 1 项" in body


# --------------------------------------------------------------------------
# 10. 渲染失败语义（cli-contract §4：exit_code=10）
# --------------------------------------------------------------------------


class TestRenderErrors:
    def test_empty_docs_raises(self, tmp_path):
        with pytest.raises(rh.RenderHtmlError) as exc:
            render([], tmp_path / "x.html")
        assert exc.value.exit_code == 10

    def test_mixed_inspection_id_raises(self, tmp_path):
        docs = fixture_docs()
        docs[1]["inspection_id"] = "insp-other"
        with pytest.raises(rh.RenderHtmlError, match="inspection_id"):
            render(docs, tmp_path / "x.html")

    def test_non_mapping_doc_raises(self, tmp_path):
        with pytest.raises(rh.RenderHtmlError):
            render(["not-a-doc"], tmp_path / "x.html")

    def test_missing_template_raises(self, tmp_path):
        with pytest.raises(rh.RenderHtmlError, match="模板读取失败") as exc:
            rh.render_html(
                fixture_docs(),
                out_path=tmp_path / "x.html",
                template=tmp_path / "nope.html",
            )
        assert exc.value.exit_code == 10

    def test_from_files_corrupt_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(rh.RenderHtmlError, match="JSON 解析失败"):
            rh.render_html_from_files([bad], out_path=tmp_path / "x.html")

    def test_from_files_missing(self, tmp_path):
        with pytest.raises(rh.RenderHtmlError, match="读取失败"):
            rh.render_html_from_files([tmp_path / "nope.json"], out_path=tmp_path / "x.html")

    def test_from_files_non_object_doc(self, tmp_path):
        bad = tmp_path / "arr.json"
        bad.write_text("[]", encoding="utf-8")
        with pytest.raises(rh.RenderHtmlError, match="不是 host-result-v1 文档"):
            rh.render_html_from_files([bad], out_path=tmp_path / "x.html")

    def test_render_error_does_not_modify_docs(self, tmp_path):
        """失败路径不改动传入文档（只读性）。"""
        docs = fixture_docs()
        import copy
        snapshot = copy.deepcopy(docs)
        with pytest.raises(rh.RenderHtmlError):
            render([docs[0], {"inspection_id": "other"}], tmp_path / "x.html")
        assert docs == snapshot


# --------------------------------------------------------------------------
# 11. render_html_from_files（HR §5 hosts/<host>.json 事实源文件）
# --------------------------------------------------------------------------


class TestFromFiles:
    def _write_hosts(self, tmp_path) -> list:
        docs = fixture_docs()
        paths = []
        for doc in docs:
            p = tmp_path / (doc["host"]["name"] + ".json")
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.append(p)
        return paths

    def test_renders_all_hosts(self, tmp_path):
        paths = self._write_hosts(tmp_path)
        out = rh.render_html_from_files(paths, out_path=tmp_path / "from-files.html")
        body = body_text(out.read_text(encoding="utf-8"))
        for host in ("node-fx01", "node-fx02", "node-fx03"):
            assert host in body

    def test_default_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        paths = self._write_hosts(tmp_path)
        out = rh.render_html_from_files(paths)
        assert out.name == INSPECTION_ID + ".html"
        assert (tmp_path / out.name).is_file()


# --------------------------------------------------------------------------
# 12. 模板渲染完整性
# --------------------------------------------------------------------------


class TestTemplateRender:
    def test_no_placeholder_leftover(self, tmp_path):
        """渲染产物（正文）无残留模板占位符。"""
        body = body_text(render_str(fixture_docs(), tmp_path))
        assert PLACEHOLDER_RE.findall(body) == []

    def test_title_and_generated_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rh, "datetime", _FixedNow)
        s = render_str(fixture_docs(), tmp_path)
        assert "<title>" + INSPECTION_ID + " — 巡检 HTML 报表</title>" in s
        assert "生成时间：2026-08-15T12:00:00" in s
        assert "<dt>生成时间</dt><dd>2026-08-15T12:00:00" in s
