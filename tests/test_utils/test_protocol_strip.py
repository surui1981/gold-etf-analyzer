"""miniMax 原生 tool-call 协议剥离（V0.120.3 回归）

⚠️ **样本全部来自生产库真实污染消息**（2026-11-02 实测 8 条），
不是手写的「示意样本」—— 手写样本会漏掉真实格式的变体
（零宽空格、`[u=functions.X]` 残留、纯 JSON 载荷行…）。

被测缺陷：上游会话畸形时 miniMax 把自己的 tool-call 协议当正文吐出，
用户在 /ask 页看到的是 `]<]minimax[>[<tool_call> {"name":…}` 这类垃圾。

覆盖：
1. 8 条真实污染样本 ⇒ 清洗后**不含任何协议标记**，且散文前缀保留
2. 正常回答 ⇒ **逐字节不变**（清洗器不能误伤）
3. 流式清洗 ⇒ 与批量清洗结果一致（标记跨 delta 断裂也能识别）
4. 流式清洗 ⇒ 标记之前的散文**不会被吞掉**
"""

from __future__ import annotations

from app.utils.protocol_strip import ProtocolStripper, strip_protocol_markup

# ────────────── 生产库真实污染样本（8 条） ──────────────

POLLUTED_SAMPLES = [
    ']<]minimax[>[<tool_call>\n]<]minimax[>[<invoke tool"> "get_market_overview" code:\n]<]minimax[>[</input>]<]minimax[>[</invoke>]<]minimax[>[</invoke>]<]minimax[>[</tool_call>',
    "]<]minimax[>[<tool_call>\n]<]minimax[>[u=functions.get_market_data]<]minimax[>[</input>]<]minimax[>[</invoke>\n]<]minimax[>[</tool_call>",
    ']<]minimax[>[<tool_call>\n]<]minimax[>[<invoke name="get_market_data">]<]minimax[>[</invoke>\n]<]minimax[>[</tool_call>',
    "### 先看结论\n\n我先拉取最新的大盘行情、市场评分和 ETF 资金流，再判断当前是普涨、结构性行情还是资金避险。]<]minimax[>[<tool_call>\n## 数据支撑\n\n正在读取最新只读数据。",
    "### 结论\n我先查询最新市场行情，确认今天的金价及日内涨跌。]<]minimax[>[<tool_call>\n]<]minimax[>[ut> ]<]minimax[>[</ut>",
    '### 结论\n我先拉取今天的最新金价与行情指标，再给你判断走势和风险。]<]minimax[>[<tool_call>\n]<]minimax[>[<invoke name="<tool_call>\n{"name":"get_market_data","arguments":{"asset":"gold"}}\n</tool_call>',
    '我先查询今天的黄金行情及金价相关指标。]<]minimax[>[<tool_call>\n]<]minimax[>[<invoke\n]<]minimax[>[<tool_call>\n{"name":"get_market_data","arguments":{"query":"今天黄金现货价格、COMEX黄金期货、上海金Au99.99，以及涨跌幅和更新时间"}}\n</tool_call>',
    "]<]minimax[>[<tool_call>\n\ninvoke_market_data]<]minimax[>[</invoke>\n]<]minimax[>[</tool_call>",
]

# 协议标记特征（清洗后一个都不能有）
FORBIDDEN = ("minimax", "tool_call", "</invoke>", "<invoke", "</input>", "<ut>", '"arguments"')


def _assert_clean(text: str) -> None:
    for token in FORBIDDEN:
        assert token not in text, f"清洗后仍残留协议标记 {token!r}: {text!r}"


def test_all_real_polluted_samples_are_cleaned() -> None:
    """8 条真实污染消息 ⇒ 清洗后无协议标记。"""
    assert len(POLLUTED_SAMPLES) == 8
    for raw in POLLUTED_SAMPLES:
        cleaned = strip_protocol_markup(raw)
        _assert_clean(cleaned)


def test_readable_prose_prefix_is_preserved() -> None:
    """污染消息里**哨兵之前的散文**必须保留（不能整段丢掉）。"""
    # 这条的散文在哨兵之前，且哨兵之后还有真正的正文（## 数据支撑）
    raw = next(s for s in POLLUTED_SAMPLES if "先看结论" in s)
    cleaned = strip_protocol_markup(raw)
    assert "我先拉取最新的大盘行情" in cleaned
    assert "## 数据支撑" in cleaned, "哨兵之后的真正文被误删了"
    assert "正在读取最新只读数据。" in cleaned


def test_normal_answer_is_byte_identical() -> None:
    """没有协议标记的正常回答 ⇒ 逐字节不变（清洗器不能误伤）。"""
    normal = (
        "## 今日金价概览\n\n"
        "**纽约金 COMEX**\n"
        "- 最新收盘价：**4736.37 美元/盎司**\n"
        "- 综合趋势指数：**44.2**\n\n"
        "> 数据截至 2026-11-02\n"
    )
    assert strip_protocol_markup(normal) == normal


def test_streaming_matches_batch_output() -> None:
    """流式清洗（逐字喂入）⇒ 结果与批量清洗一致。

    ⚠ 只比 ``.strip()`` 后的结果：批量路径末尾会 ``.strip()``，
    流式路径**没法回溯**去删已经吐出去的换行 ⇒ 首尾空白允许有差异。
    """
    for raw in POLLUTED_SAMPLES:
        stripper = ProtocolStripper()
        streamed = "".join(stripper.feed(ch) for ch in raw) + stripper.flush()
        assert streamed.strip() == strip_protocol_markup(raw).strip(), f"流式与批量不一致: {raw!r}"


def test_streaming_emits_prose_before_marker() -> None:
    """流式清洗：哨兵之前的散文**必须被吐出来**（不能被缓冲吞掉）。"""
    raw = next(s for s in POLLUTED_SAMPLES if "我先查询今天的黄金行情" in s)
    stripper = ProtocolStripper()
    chunks = [stripper.feed(raw[i : i + 7]) for i in range(0, len(raw), 7)]
    streamed = "".join(chunks) + stripper.flush()
    assert "我先查询今天的黄金行情及金价相关指标。" in streamed
    _assert_clean(streamed)


def test_streaming_split_marker_is_still_detected() -> None:
    """哨兵被切在两个 delta 中间 ⇒ 仍要识别（不能漏检）。"""
    stripper = ProtocolStripper()
    # 故意在哨兵中间切开
    out = stripper.feed("前置散文。]<]mi") + stripper.feed("nimax[>[<tool_call>\n后置散文。")
    out += stripper.flush()
    _assert_clean(out)
    assert "前置散文。" in out
