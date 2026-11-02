"""剥离 miniMax 原生 tool-call 协议标记（V0.120.3）。

为什么需要这个模块
------------------
V0.120.3 实测根因：我们回传给上游的 ``messages`` **缺 assistant 的 tool_use 回合**，
而 Anthropic 协议要求 ``assistant(tool_use) → user(tool_result)`` 配对。
缺了 assistant 回合 ⇒ 上游收到畸形会话 ⇒ miniMax 退化，**把自己的原生
tool-call 协议当正文吐出来**，用户看到的是这样一坨：

    我先查询今天的黄金行情及金价相关指标。][SENTINEL][<tool_call>
    ][SENTINEL][<invoke
    ][SENTINEL][<tool_call>
    {"name":"get_market_data","arguments":{"query":"今天黄金现货价格…"}}
    </tool_call>

协议标记的形态（生产库 10 条污染消息实测）
------------------------------------------
| 成分 | 例子 | 备注 |
|---|---|---|
| 哨兵 | ``]<]minimax[>[`` | 12 个 ASCII 字符（可能夹零宽空格变体）|
| 标签 | ``<tool_call>`` ``<invoke`` ``</input>`` ``<ut>`` | 尖括号标签 |
| 载荷 | ``{"name":"get_market_data","arguments":{…}}`` | 裸 JSON |
| 残留 | ``[u=functions.get_market_data]`` | OpenAI 风格函数标记 |

清洗规则（逐行）
----------------
1. **行内出现哨兵 ⇒ 只保留哨兵之前的散文前缀**，行内其余部分整段丢弃。
   （实测 10 条污染消息：这一条规则就解决了大部分；剩下的靠规则 2/3。）
2. 纯协议标签 / OpenAI 风格函数标记 ⇒ 删掉标签本身。
3. 整行是 ``{"name": …}`` 形态的 JSON ⇒ 整行丢弃（那是工具调用载荷，不是答案）。
4. 哨兵之前的纯标识符前缀（如幻觉工具名 ``invoke_market_data``）⇒ 丢弃。

⚠ **只对 assistant 消息生效**：tool 消息的正文**本身就是** JSON（含 ``name`` 键），
套规则 3 会把工具数据整段毁掉。调用方必须自己保证只清洗 assistant 正文。
"""

from __future__ import annotations

import json
import re

# ────────────── 协议标记 ──────────────

# 零宽字符（miniMax 有时插在标记中间，用来规避简单过滤）
_ZW_CHARS = "\u200b\u200c\u200d\u2060\ufeff"
_ZW_OPT = "(?:[" + re.escape(_ZW_CHARS) + "])?"

# 哨兵：每一段协议内容都以它开头（"]<]minimax[>"，各段之间可能夹零宽字符）
_SENTINEL_RE = re.compile(r"\]" + _ZW_OPT + r"<\]" + _ZW_OPT + r"minimax" + _ZW_OPT + r"\[>")

# 协议标签（开闭标签都覆盖）
_TAG_RE = re.compile(
    r"<"
    + _ZW_OPT
    + r"/?\s*(?:tool_call|tool_result|function_calls|invoke|argument|arguments|input|ut)\b[^>]*>",
    re.IGNORECASE,
)

# OpenAI 风格函数调用残留
_U_FUNC_RE = re.compile(r"\[u=functions\.[A-Za-z0-9_.\-]+\]")

# 纯标识符（幻觉工具名，如 invoke_market_data）
_BARE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 连续空行折叠
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _clean_line(line: str) -> str:
    """清洗单行文本（协议标记只可能在 assistant 正文里出现）。"""
    # 规则 1：行内出现哨兵 ⇒ 只保留哨兵之前的散文前缀
    m = _SENTINEL_RE.search(line)
    if m:
        prefix = line[: m.start()]
        stripped_prefix = prefix.strip()
        # 规则 4：纯标识符前缀 = 幻觉工具名残留 ⇒ 丢弃
        if stripped_prefix and _BARE_IDENT_RE.match(stripped_prefix):
            prefix = ""
        line = prefix

    # 规则 2：协议标签 / OpenAI 风格函数标记
    line = _TAG_RE.sub("", line)
    line = _U_FUNC_RE.sub("", line)

    # 规则 3：整行是 {"name": …} 形态的 JSON ⇒ 工具调用载荷，整行丢弃
    body = line.strip()
    if body.startswith("{") and body.endswith("}"):
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and "name" in parsed:
            line = ""

    return line


def strip_protocol_markup(text: str) -> str:
    """批量清洗 assistant 正文里的 miniMax 原生协议标记。

    ⚠ **只对 assistant 正文调用**：tool 消息正文本身就是 JSON（含 ``name`` 键），
    套规则 3 会被整段清掉。

    Args:
        text: assistant 正文。

    Returns:
        清洗后的文本；**不含任何协议标记**。
        没有协议标记时原样返回（不做任何改写 ⇒ 正常回答零影响）。
    """
    if not text:
        return text
    if _SENTINEL_RE.search(text) is None:
        # 没有哨兵 ⇒ 不存在协议段 ⇒ 原样返回（保护正常回答不被误伤）
        return text
    cleaned = "\n".join(_clean_line(line) for line in text.split("\n"))
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


class ProtocolStripper:
    """流式增量清洗器（逐 delta 喂入，标记跨 delta 也能识别）。

    用法::

        stripper = ProtocolStripper()
        for delta in upstream_deltas:
            safe = stripper.feed(delta)
            if safe:
                yield safe
        tail = stripper.flush()

    ⚠ **必须走完 flush()**：最后一段（可能不足一行）留在缓冲区里，
    不 flush 会丢掉尾部文本。
    """

    # fast 模式下的保留窗口：必须 ≥ 哨兵最长长度（15），否则跨 chunk 的哨兵会漏检
    _HOLD = 24

    def __init__(self) -> None:
        self._buf = ""
        self._line_mode = False
        self._last_blank = False

    def feed(self, chunk: str) -> str:
        """喂入一段增量，返回**可以安全输出**的文本。"""
        if not chunk:
            return ""
        self._buf += chunk

        if not self._line_mode:
            m = _SENTINEL_RE.search(self._buf)
            if m is None:
                # 没有哨兵 ⇒ 快速通道：只保留尾部窗口，防止哨兵跨 chunk 漏检
                if len(self._buf) <= self._HOLD:
                    return ""
                out = self._buf[: -self._HOLD]
                self._buf = self._buf[-self._HOLD :]
                return out
            # 命中哨兵 ⇒ 切逐行模式。
            # head 是尚未输出的部分：换行之前的完整行直接输出；
            # 换行之后到哨兵之前是「当前行的散文前缀」⇒ 留在缓冲区，由 _clean_line 保留。
            self._line_mode = True
            head = self._buf[: m.start()]
            nl = head.rfind("\n")
            if nl >= 0:
                out = head[: nl + 1]
                self._buf = head[nl + 1 :] + self._buf[m.start() :]
            else:
                out = ""
                self._buf = head + self._buf[m.start() :]
            return out + self._drain_lines()

        return self._drain_lines()

    def flush(self) -> str:
        """流结束：处理缓冲区里最后一段（可能不足一行）。"""
        rest = self._buf
        self._buf = ""
        if not rest:
            return ""
        return _clean_line(rest)

    def _drain_lines(self) -> str:
        """清洗所有**完整行**（以换行结尾）；末尾不完整行留在缓冲区。"""
        if "\n" not in self._buf:
            return ""
        idx = self._buf.rfind("\n")
        complete = self._buf[: idx + 1]
        self._buf = self._buf[idx + 1 :]
        parts = complete.split("\n")[:-1]  # 去掉末尾空串（换行本身）
        out: list[str] = []
        for line in parts:
            cleaned = _clean_line(line)
            blank = not cleaned.strip()
            # 连续空行只保留一个（协议段落被剥掉后会留下一串空行）
            if blank and self._last_blank:
                continue
            self._last_blank = blank
            out.append(cleaned + "\n")
        return "".join(out)
