"""V0.73.0+ i18n.apply() DOM 应用行为测试。

**为什么需要这个文件**：
PR-N+8 / PR-N+9 大批量加 `data-i18n` 时，未考虑 inline child 节点（如 `<span id="badge">` /
`<span id="clSum">` / `<button id="refreshBtn">`）会被 i18n.apply() 的 `el.textContent = ...`
一并擦掉，导致后续 JS `getElementById(...)` 拿到 null 报错（典型：`Cannot set properties of
null (setting 'textContent')`）。

**本测试覆盖**：
- 单文本节点 → 翻译替换
- 文本 + 内联元素 → 翻译更新 + 内联元素保留
- 仅有内联元素 → 翻译以新文本节点前插
- 多文本节点 → 第一个保留并替换，其余移除
- [data-i18n-html] / [data-i18n-placeholder] / [data-i18n-title] / [data-i18n-aria] 不受影响
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
NODE = "node"


HARNESS = textwrap.dedent("""
    // 更完整的 DOM mock：支持 childNodes / TEXT_NODE
    function makeEl(tagName) {
      const el = {
        tagName: tagName || "DIV",
        nodeType: 1, // ELEMENT_NODE
        children: [],
        childNodes: [],
        attributes: {},
        dataset: {},
        get firstChild() { return this.childNodes[0] || null; },
        get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; },
        setAttribute(k, v) { this.attributes[k] = String(v); },
        getAttribute(k) { return this.attributes[k] != null ? this.attributes[k] : null; },
        querySelector: () => null,
        querySelectorAll: () => [],
        appendChild(c) {
          if (c.nodeType === 3) {
            this.childNodes.push(c);
          } else {
            this.children.push(c);
            this.childNodes.push(c);
          }
          c.parentNode = this;
          return c;
        },
        insertBefore(newNode, refNode) {
          const idx = refNode == null ? this.childNodes.length : this.childNodes.indexOf(refNode);
          this.childNodes.splice(idx, 0, newNode);
          if (newNode.nodeType !== 3) this.children.splice(idx, 0, newNode);
          newNode.parentNode = this;
          return newNode;
        },
        removeChild(child) {
          const i = this.childNodes.indexOf(child);
          if (i >= 0) this.childNodes.splice(i, 1);
          const j = this.children.indexOf(child);
          if (j >= 0) this.children.splice(j, 1);
        },
        classList: { add: () => {}, remove: () => {} },
      };
      return el;
    }
    function makeTextNode(value) {
      return { nodeType: 3, nodeValue: String(value), parentNode: null };
    }

    const root = makeEl("BODY");
    // 关键：apply() 内部调用 root.querySelectorAll（不是 document.querySelectorAll）
    root.querySelectorAll = function () { return collectAll(root, []); };

    // querySelectorAll 递归查找 [data-i18n*] 元素
    function collectAll(node, out) {
      out = out || [];
      for (const c of node.children || []) {
        const ds = c.dataset || {};
        const has =
          ds.i18n != null ||
          ds.i18nHtml != null ||
          ds.i18nPlaceholder != null ||
          ds.i18nTitle != null ||
          ds.i18nAria != null;
        if (has) out.push(c);
        collectAll(c, out);
      }
      return out;
    }

    const document = {
      documentElement: makeEl("HTML"),
      body: root,
      readyState: "complete",
      addEventListener: () => {},
      querySelector: () => null,
      querySelectorAll: () => [],
      getElementById: () => null,
      createElement: (t) => makeEl(t || "DIV"),
      createTextNode: (v) => makeTextNode(v),
      head: { appendChild: () => {} },
      dispatchEvent: () => {},
    };
    document.querySelectorAll = function (sel) { return collectAll(root, []); };
    const window = globalThis;
    window.document = document;
    window.localStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); } };
    window.CustomEvent = function (n, i) { return { type: n, detail: i ? i.detail : null }; };

    // 加载字典
    const fs = require('fs');
    function loadDict(file) {
      const t = fs.readFileSync(file, 'utf8');
      const m = t.match(/window\\.PM_I18N_\\w+\\s*=\\s*({[\\s\\S]*?});?\s*$/);
      if (!m) throw new Error('dict not found in ' + file);
      return eval('(' + m[1] + ')');
    }
    window.PM_I18N_ZH_CN = loadDict('{STATIC}/i18n/zh-CN.js');
    window.PM_I18N_en_US = loadDict('{STATIC}/i18n/en-US.js');

    // 加载 i18n.js
    eval(fs.readFileSync('{STATIC}/i18n.js', 'utf8'));

    {js_body}

    console.log(JSON.stringify({ result: typeof result !== "undefined" ? result : null }));
""").strip()


def _run(js_body: str):
    proc = subprocess.run(
        [NODE, "-e", HARNESS.replace("{js_body}", js_body).replace("{STATIC}", str(STATIC))],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Node failed: stderr={proc.stderr}; stdout={proc.stdout}")
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(last)["result"]


# ── 测试用例 ──


def test_apply_preserves_inline_child_with_text_node():
    """data-i18n 元素的 inline 子元素应被保留（修复 V0.73.0 PR-N+8 回归）。"""
    # 在 Node 中构造场景
    out = _run(textwrap.dedent("""
        const h1 = makeEl("h1");
        h1.attributes["data-i18n"] = "trend.h1";
        h1.dataset["i18n"] = "trend.h1";
        const t = makeTextNode("前缀 ");
        const badge = makeEl("span");
        badge.attributes["id"] = "badge";
        const btn = makeEl("button");
        btn.attributes["id"] = "refreshBtn";
        h1.appendChild(t);
        h1.appendChild(badge);
        h1.appendChild(btn);
        document.body.appendChild(h1);  // 必须挂到 body 才能被 collectAll 找到

        window.I18n.apply(document.body);

        result = {
          badgeStillExists: h1.children.indexOf(badge) >= 0,
          btnStillExists: h1.children.indexOf(btn) >= 0,
          textNodeValue: t.nodeValue,
          textNodeStillFirst: h1.childNodes[0] === t,
          childCount: h1.childNodes.length,
        };
    """))
    assert out["badgeStillExists"] is True, "inline <span id=badge> 被 apply() 误删"
    assert out["btnStillExists"] is True, "inline <button id=refreshBtn> 被 apply() 误删"
    assert "黄金价格投资辅助工具" in out["textNodeValue"], f"翻译未生效：{out['textNodeValue']!r}"
    assert out["textNodeStillFirst"] is True, "文本节点位置错乱"
    assert out["childCount"] == 3, f"子节点数量错乱：{out['childCount']}"


def test_apply_with_only_inline_children_prepends_text():
    """data-i18n 元素只有 inline children（无文本节点）时，应前插新文本节点。"""
    out = _run(textwrap.dedent("""
        const p = makeEl("p");
        p.attributes["data-i18n"] = "trend.h1";
        p.dataset["i18n"] = "trend.h1";
        const icon = makeEl("i");
        icon.attributes["id"] = "icon";
        p.appendChild(icon);
        document.body.appendChild(p);

        window.I18n.apply(document.body);

        result = {
          iconStillExists: p.children.indexOf(icon) >= 0,
          firstChildIsText: p.childNodes[0].nodeType === 3,
          firstChildValue: p.childNodes[0].nodeValue,
        };
    """))
    assert out["iconStillExists"] is True, "inline <i id=icon> 被误删"
    assert out["firstChildIsText"] is True, "未前插文本节点"
    assert "黄金价格投资辅助工具" in out["firstChildValue"]


def test_apply_collapses_multiple_text_nodes():
    """data-i18n 元素有多个文本节点时，合并为第一个并替换，其余移除。"""
    out = _run(textwrap.dedent("""
        const div = makeEl("div");
        div.attributes["data-i18n"] = "trend.h1";
        div.dataset["i18n"] = "trend.h1";
        const t1 = makeTextNode("aaa ");
        const t2 = makeTextNode("bbb ");
        const t3 = makeTextNode("ccc");
        div.appendChild(t1);
        div.appendChild(t2);
        div.appendChild(t3);
        document.body.appendChild(div);

        window.I18n.apply(document.body);

        result = {
          textNodeCount: div.childNodes.filter(n => n.nodeType === 3).length,
          firstValue: t1.nodeValue,
          t2Removed: div.childNodes.indexOf(t2) < 0,
          t3Removed: div.childNodes.indexOf(t3) < 0,
        };
    """))
    assert out["textNodeCount"] == 1, f"应只保留 1 个文本节点，实际 {out['textNodeCount']}"
    assert "黄金价格投资辅助工具" in out["firstValue"]
    assert out["t2Removed"] is True, "多余文本节点未移除"
    assert out["t3Removed"] is True, "多余文本节点未移除"


def test_apply_plain_text_element_still_works():
    """data-i18n 元素纯文本（无子元素）应正常翻译。"""
    out = _run(textwrap.dedent("""
        const span = makeEl("span");
        span.attributes["data-i18n"] = "trend.h1";
        span.dataset["i18n"] = "trend.h1";
        span.appendChild(makeTextNode("old text"));
        document.body.appendChild(span);

        window.I18n.apply(document.body);

        result = span.childNodes[0].nodeValue;
    """))
    assert "黄金价格投资辅助工具" in out


def test_apply_attribute_keys_unaffected():
    """[data-i18n-placeholder] / [data-i18n-title] / [data-i18n-aria] 走 setAttribute，不影响 children。"""
    out = _run(textwrap.dedent("""
        const input = makeEl("input");
        input.attributes["data-i18n-placeholder"] = "common.search";
        input.dataset["i18nPlaceholder"] = "common.search";
        const originalChild = makeEl("span");
        input.appendChild(originalChild);
        document.body.appendChild(input);

        window.I18n.apply(document.body);

        result = {
          placeholder: input.attributes["placeholder"] || null,
          childStillExists: input.children.indexOf(originalChild) >= 0,
        };
    """))
    # zh-CN dict has common.search
    assert out["placeholder"] is not None and out["placeholder"] != "", f"placeholder={out['placeholder']!r}"
    assert out["childStillExists"] is True