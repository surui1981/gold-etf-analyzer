/* static/ask.js — V0.97.0 智能分析页 chat 逻辑
 *
 * 职责：
 *   1. 启动时 GET /api/v1/ai/health → 决定显示 disabledCover 还是 3 pane
 *   2. 列对话（GET /conversations）→ 渲染侧边栏
 *   3. 点对话 → GET /conversations/{id} → 渲染消息流
 *   4. 发消息（POST /conversations/{id}/messages）→ 渲染 assistant + tool
 *   5. 工具调用 → 渲染右侧 tool trace
 *   6. XSS 防护：marked 解析后清洗 script/iframe/事件属性/javascript URI
 *   7. i18n：跟随全局 pm_lang 切换（i18n.js 已处理 data-i18n）
 *
 * ⚠ V0.97.0 简版：同步请求，不做流式；发送中 button 禁用 + 「发送中…」
 */

(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var convListEl = $('convList');
  var streamEl = $('messageStream');
  var inputEl = $('msgInput');
  var sendBtn = $('btnSend');
  var newBtn = $('btnNewChat');
  var titleEl = $('convTitle');
  var actionsEl = $('convActions');
  var renameBtn = $('btnRename');
  var archiveBtn = $('btnArchive');
  var toolTraceEl = $('toolTrace');
  var toolTraceListEl = $('toolTraceList');
  var toolCountEl = $('toolCount');
  var disabledCover = $('disabledCover');
  var askLayout = $('askLayout');
  var quotaLine = $('quotaLine');

  var state = {
    enabled: false,
    conversations: [],
    activeId: null,
    messages: [],
    sending: false,
    health: null,
  };

  // ────────────── 工具 ──────────────

  function t(key, fallback) {
    if (window.I18n && typeof window.I18n.t === 'function') {
      var v = window.I18n.t(key);
      if (v) return v;
    }
    return fallback || key;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** 简易 XSS 清洗：移除 <script>/<iframe>，剥离 on* 事件与 javascript: URI。 */
  function sanitizeHtml(html) {
    if (!html) return '';
    return String(html)
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/<object[\s\S]*?<\/object>/gi, '')
      .replace(/<embed[\s\S]*?<\/embed>/gi, '')
      .replace(/\s(onc(?:lick|load|error|mouseover|focus|blur|change|submit)\s*=\s*["'][^"']*["'])/gi, '')
      .replace(/(href|src)\s*=\s*["']\s*javascript:[^"']*["']/gi, '$1="#"');
  }

  function renderMarkdown(text) {
    if (!text) return '';
    if (typeof window.marked === 'undefined' || !window.marked.parse) {
      return '<p>' + escapeHtml(text) + '</p>';
    }
    try {
      var html = window.marked.parse(text, { breaks: true, gfm: true, mangle: false, headerIds: false });
      return sanitizeHtml(html);
    } catch (e) {
      return '<p>' + escapeHtml(text) + '</p>';
    }
  }

  function formatTime(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      var now = new Date();
      var diff = (now - d) / 1000;
      if (diff < 60) return t('ai.time_just_now', '刚刚');
      if (diff < 3600) return Math.floor(diff / 60) + ' ' + t('ai.time_minute', '分钟前');
      if (diff < 86400) return Math.floor(diff / 3600) + ' ' + t('ai.time_hour', '小时前');
      var m = (d.getMonth() + 1).toString().padStart(2, '0');
      var dd = d.getDate().toString().padStart(2, '0');
      return m + '-' + dd;
    } catch (e) { return ''; }
  }

  function el(tag, attrs, children) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'html') e.innerHTML = attrs[k];
      else if (k === 'text') e.textContent = attrs[k];
      else if (k.indexOf('on') === 0 && typeof attrs[k] === 'function') e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    if (children) children.forEach(function (c) {
      if (typeof c === 'string') e.appendChild(document.createTextNode(c));
      else if (c) e.appendChild(c);
    });
    return e;
  }

  // ────────────── Tool 展示（V0.97.0 hotfix）──────────────

  // 英文 tool 名 → 中文友好标签（trace 面板 / chat chip 通用）
  var TOOL_LABELS = {
    get_market_overview: '📈 市场概览',
    get_scoring_summary: '🎯 评分汇总',
    get_user_portfolio: '💼 持仓查询',
    get_warning_summary: '⚠️ 警示',
    get_etf_recent_flows: '💸 ETF 资金流',
  };

  function toolLabel(name) {
    return TOOL_LABELS[name] || ('🔧 ' + name);
  }

  /** 抽取 tool input 的关键展示字段（已知 tool 类型用白名单，其他原样）。 */
  function summarizeInput(tool, input) {
    if (!input) return '';
    if (tool === 'get_scoring_summary') {
      return (input.from || '?') + ' → ' + (input.to || '?');
    }
    if (tool === 'get_etf_recent_flows') {
      return '近 ' + (input.days || 30) + ' 天';
    }
    try { return JSON.stringify(input); } catch (_) { return String(input); }
  }

  /** 从 tool result JSON 抽取 1-3 个核心字段做摘要（已知 tool 走白名单）。 */
  function summarizeResult(tool, raw) {
    if (!raw) return '';
    var obj;
    try { obj = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (_) { return truncate(raw, 200); }
    if (tool === 'get_market_overview' && obj && obj.markets) {
      // 列出每个市场的最新价
      var lines = [];
      Object.keys(obj.markets).forEach(function (k) {
        var m = obj.markets[k];
        if (m && m.close != null) lines.push(k + ': ' + m.close + ' (' + (m.change_pct_1d != null ? (m.change_pct_1d > 0 ? '+' : '') + m.change_pct_1d + '%' : '—') + ')');
      });
      return lines.join(' · ');
    }
    if (tool === 'get_scoring_summary' && obj && obj.mini_card) {
      var mc = obj.mini_card;
      var last30 = mc.last_30d || {};
      return '近 30d T+0/T+1/T+3/T+5: ' +
        [last30.t0, last30.t1, last30.t3, last30.t5]
          .map(function (v) { return v == null ? '—' : (Math.round(v * 1000) / 10) + '%'; })
          .join(' / ') +
        ' · 最佳: ' + (mc.best_horizon || '—');
    }
    if (tool === 'get_user_portfolio' && obj) {
      return [
        '成本 ' + (obj.total_cost != null ? obj.total_cost.toFixed(0) : '—'),
        '市值 ' + (obj.total_invested != null ? obj.total_invested.toFixed(0) : '—'),
        '浮盈 ' + (obj.unrealized_pnl != null ? (obj.unrealized_pnl > 0 ? '+' : '') + obj.unrealized_pnl.toFixed(0) : '—'),
        '收益率 ' + (obj.total_return_pct != null ? obj.total_return_pct + '%' : '—'),
      ].join(' · ');
    }
    if (tool === 'get_warning_summary' && obj && obj.markets) {
      return Object.keys(obj.markets).length + ' 个市场状态';
    }
    if (tool === 'get_etf_recent_flows' && obj && obj.bars) {
      var first = obj.bars[0], last = obj.bars[obj.bars.length - 1];
      return obj.bars.length + ' 天 · 最近: ' + (last && last.date ? last.date : '—');
    }
    // 未知 tool：截断 JSON
    var s = typeof raw === 'string' ? raw : JSON.stringify(obj);
    return truncate(s, 200);
  }

  function truncate(s, n) {
    s = String(s);
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  // ────────────── API ──────────────

  function apiGet(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return { detail: r.statusText }; })
          .then(function (body) { throw new Error(body.detail || (t('ai.error_http', 'HTTP ') + r.status)); });
      }
      return r.json();
    });
  }

  function apiSend(url, method, body) {
    return fetch(url, {
      method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return { detail: r.statusText }; })
          .then(function (b) {
            var err = new Error(b.detail || ('HTTP ' + r.status));
            err.status = r.status; err.body = b;
            throw err;
          });
      }
      if (r.status === 204) return null;
      return r.json();
    });
  }

  // ────────────── 启动 ──────────────

  function init() {
    return apiGet('/api/v1/ai/health')
      .then(function (data) {
        state.health = data;
        state.enabled = data.enabled;
        if (data.enabled) {
          askLayout.hidden = false;
          renderQuota(data);
          return loadConversations();
        } else {
          disabledCover.hidden = false;
        }
      })
      .catch(function (err) {
        // 401 时 dev 模式无 user，但 health 端点不需鉴权
        console.warn('health check failed', err);
        disabledCover.hidden = false;
        // 区分 401（未登录）和 503（未配置）
        if (err && err.status === 401) {
          disabledCover.querySelector('h2').textContent = t('ai.disabled_title_auth', '请先登录');
          disabledCover.querySelector('p').textContent = t('ai.disabled_body_auth', '智能分析需要登录后才能使用。');
        }
      });
  }

  function renderQuota(health) {
    if (health && health.per_user_per_minute) {
      quotaLine.textContent = t('ai.quota_line', '限速 {rpm} req/min · 配额 {quota} tokens/天')
        .replace('{rpm}', health.per_user_per_minute)
        .replace('{quota}', (health.daily_token_quota / 1000) + 'k');
    }
  }

  // ────────────── 对话列表 ──────────────

  function loadConversations() {
    return apiGet('/api/v1/ai/conversations?limit=50')
      .then(function (rows) {
        state.conversations = rows || [];
        renderConvList();
      })
      .catch(function (err) {
        if (err.status === 401) {
          disabledCover.hidden = false;
          askLayout.hidden = true;
          return;
        }
        showBanner('err', t('ai.error_load_conv', '加载对话失败：') + err.message);
      });
  }

  function renderConvList() {
    convListEl.innerHTML = '';
    if (!state.conversations.length) {
      var empty = el('li', { class: 'empty-conv' });
      empty.textContent = t('ai.empty_conv_list', '还没有对话');
      convListEl.appendChild(empty);
      return;
    }
    state.conversations.forEach(function (c) {
      var item = el('li', { class: 'conv-item' + (c.id === state.activeId ? ' active' : ''), 'data-id': c.id, onclick: function () { openConversation(c.id); } }, [
        el('span', { class: 'title', text: c.title || t('ai.untitled', '未命名对话') }),
        el('div', { class: 'meta' }, [
          el('span', { class: 'time', text: formatTime(c.last_message_at) }),
          el('span', { class: 'count', text: c.message_count + ' ' + t('ai.msg_count_unit', '条') }),
          el('span', { class: 'archive', title: t('ai.archive', '归档'), onclick: function (ev) { ev.stopPropagation(); archiveConv(c.id); } }, ['×']),
        ]),
      ]);
      convListEl.appendChild(item);
    });
  }

  // ────────────── 单对话 + 消息流 ──────────────

  function openConversation(convId) {
    state.activeId = convId;
    state.messages = [];
    renderConvList();
    renderEmptyStream();
    actionsEl.hidden = false;
    return apiGet('/api/v1/ai/conversations/' + convId)
      .then(function (detail) {
        state.messages = detail.messages || [];
        var conv = detail.conversation;
        titleEl.textContent = conv.title || t('ai.untitled', '未命名对话');
        renderMessages();
      })
      .catch(function (err) {
        showBanner('err', t('ai.error_load_conv', '加载对话失败：') + err.message);
      });
  }

  function renderEmptyStream() {
    streamEl.innerHTML = '<div class="empty-stream">' + escapeHtml(t('ai.empty_state', '还没有对话 — 点左侧「+ 新对话」开始提问')) + '</div>';
    toolTraceEl.hidden = true;
    toolCountEl.textContent = '(0)';
  }

  function renderMessages() {
    if (!state.messages.length) {
      renderEmptyStream();
      return;
    }
    streamEl.innerHTML = '';
    var toolCount = 0;
    var lastAsstIdx = -1;
    state.messages.forEach(function (m, idx) {
      if (m.role === 'user') {
        streamEl.appendChild(renderUserMsg(m));
      } else if (m.role === 'assistant') {
        streamEl.appendChild(renderAssistantMsg(m));
        if (m.tool_name) toolCount++;
        if (m.content) lastAsstIdx = idx;  // 记下最终 assistant 索引
      } else if (m.role === 'tool') {
        // tool 消息：聊天流中以折叠 details 显示（V0.97.0 hotfix）
        streamEl.appendChild(renderToolMsgInStream(m));
      }
    });
    // 给最终 assistant 加「📊 数据来源」chip（如果有 tool 调用）
    if (lastAsstIdx >= 0 && toolCount > 0) {
      var lastAsstEl = streamEl.children[lastAsstIdx];
      if (lastAsstEl) {
        lastAsstEl.appendChild(el('div', {
          class: 'data-source-chip',
          text: '📊 基于 ' + toolCount + ' 个工具调用 · 右侧查看详情',
        }));
      }
    }
    updateToolTrace(toolCount);
    // 滚到底
    streamEl.scrollTop = streamEl.scrollHeight;
  }

  function renderUserMsg(m) {
    var bubble = el('div', { class: 'bubble' });
    bubble.textContent = m.content;
    return el('div', { class: 'message user' }, [
      el('div', { class: 'avatar', text: '我' }),
      bubble,
    ]);
  }

  function renderAssistantMsg(m) {
    var bubble = el('div', { class: 'bubble' });
    if (m.content) {
      bubble.innerHTML = renderMarkdown(m.content);
    } else if (m.tool_name) {
      // 已完成响应的 tool_use 消息：用 chip 显示，不再 spinner
      bubble.appendChild(el('div', {
        class: 'tool-chip',
        text: '🔧 ' + toolLabel(m.tool_name),
      }));
    }
    var meta = el('div', { class: 'meta', style: 'font-size:10.5px;color:var(--muted);margin-top:4px;display:flex;gap:8px;' });
    if (m.input_tokens != null) meta.appendChild(el('span', { text: '↓ ' + m.input_tokens }));
    if (m.output_tokens != null) meta.appendChild(el('span', { text: '↑ ' + m.output_tokens }));
    if (m.latency_ms != null) meta.appendChild(el('span', { text: Math.round(m.latency_ms / 100) / 10 + 's' }));

    var wrap = el('div', { class: 'bubble' });
    wrap.appendChild(bubble);
    if (meta.children.length) wrap.appendChild(meta);

    return el('div', { class: 'message assistant' }, [
      el('div', { class: 'avatar', text: 'AI' }),
      wrap,
    ]);
  }

  /** tool 消息：聊天流中以折叠 details 显示（默认收，展开看原始 JSON）。 */
  function renderToolMsgInStream(m) {
    var summary = summarizeResult(m.tool_name, m.content);
    var details = el('details', { class: 'tool-result-stream' });
    var sumNode = el('summary', { class: 'tool-result-summary' }, [
      el('span', { class: 'tool-name', text: toolLabel(m.tool_name) }),
      el('span', { class: 'tool-result-text', text: summary || '(无结果)' }),
    ]);
    details.appendChild(sumNode);
    details.appendChild(el('pre', {
      class: 'tool-result-raw',
      text: m.content || '',
    }));
    return el('div', { class: 'message tool-msg' }, [details]);
  }

  function updateToolTrace(count) {
    if (!count) {
      toolTraceEl.hidden = true;
      return;
    }
    toolTraceEl.hidden = false;
    toolCountEl.textContent = '(' + count + ')';
    toolTraceListEl.innerHTML = '';
    state.messages.forEach(function (m) {
      if (m.role === 'tool' || (m.role === 'assistant' && m.tool_name)) {
        toolTraceListEl.appendChild(renderToolTraceItem(m));
      }
    });
  }

  function renderToolTraceItem(m) {
    var isErr = m.error_code != null;
    var item = el('div', { class: 'tool-trace-item' + (isErr ? ' is-error' : '') });
    // 头部：工具名（中文 label）+ 角色 chip
    var name = el('div', { class: 'name' });
    name.appendChild(el('span', { text: toolLabel(m.tool_name) }));
    name.appendChild(el('span', {
      class: 'role-chip',
      text: m.role === 'assistant' ? '→ 调用' : '← 结果',
    }));
    item.appendChild(name);
    // 输入摘要
    if (m.tool_input) {
      var inputText = summarizeInput(m.tool_name, m.tool_input);
      if (inputText) item.appendChild(el('div', { class: 'input-preview', text: '参数: ' + inputText }));
    }
    // 结果摘要（关键字段抽取）
    if (m.content && m.role === 'tool') {
      var resultText = summarizeResult(m.tool_name, m.content);
      if (resultText) item.appendChild(el('div', { class: 'summary', text: resultText }));
      // 折叠：原始 JSON
      var raw = el('details', { class: 'raw-details' });
      raw.appendChild(el('summary', { text: '原始 JSON' }));
      raw.appendChild(el('pre', { text: truncate(m.content, 800) }));
      item.appendChild(raw);
    }
    return item;
  }

  // ────────────── 新对话 ──────────────

  function newConversation() {
    if (state.sending) return;
    return apiSend('/api/v1/ai/conversations', 'POST', {})
      .then(function (conv) {
        state.conversations.unshift(conv);
        state.activeId = conv.id;
        state.messages = [];
        titleEl.textContent = conv.title || t('ai.untitled', '未命名对话');
        actionsEl.hidden = false;
        renderConvList();
        renderEmptyStream();
        inputEl.focus();
      })
      .catch(function (err) {
        showBanner('err', t('ai.error_new_conv', '创建对话失败：') + err.message);
      });
  }

  // ────────────── 发消息 ──────────────

  function sendMessage() {
    if (state.sending) return;
    var text = (inputEl.value || '').trim();
    if (!text) {
      showBanner('warn', t('ai.empty_input', '请先输入问题'));
      return;
    }
    if (!state.activeId) {
      // 自动建对话
      return newConversation().then(function () { if (state.activeId) { inputEl.value = text; sendMessage(); } });
    }
    state.sending = true;
    sendBtn.disabled = true;
    sendBtn.textContent = t('ai.sending', '发送中…');
    // 清空流，加 user msg
    var userMsg = { role: 'user', content: text, created_at: new Date().toISOString() };
    state.messages.push(userMsg);
    renderMessages();
    var placeholderAsst = { role: 'assistant', content: '', tool_name: null };
    state.messages.push(placeholderAsst);
    renderMessages();
    inputEl.value = '';
    autoResize();

    return apiSend('/api/v1/ai/conversations/' + state.activeId + '/messages', 'POST', { content: text })
      .then(function (turn) {
        // 替换 placeholder + 加 responses
        state.messages = state.messages.slice(0, -1).concat(turn.responses || []);
        renderMessages();
        // bump conv 列表 last_message_at
        var conv = state.conversations.find(function (c) { return c.id === state.activeId; });
        if (conv) {
          conv.message_count = (conv.message_count || 0) + 1 + (turn.responses ? turn.responses.length - 1 : 0);
          conv.last_message_at = new Date().toISOString();
          state.conversations.sort(function (a, b) { return (b.last_message_at || '').localeCompare(a.last_message_at || ''); });
          renderConvList();
        }
      })
      .catch(function (err) {
        // 移除 placeholder，保留 user_msg（也滚回）
        state.messages = state.messages.slice(0, -2);
        if (err.status === 429) {
          showBanner('warn', t('ai.error_rate_limit', '提问太频繁，请稍后再试'));
        } else if (err.status === 503) {
          showBanner('err', t('ai.error_llm', '模型服务异常：') + (err.message || ''));
        } else {
          showBanner('err', t('ai.error_network', '网络异常：') + err.message);
        }
        renderMessages();
      })
      .then(function () {
        state.sending = false;
        sendBtn.disabled = false;
        sendBtn.textContent = t('ai.send', '发送');
        inputEl.focus();
      });
  }

  // ────────────── 归档 / 改名 ──────────────

  function archiveConv(convId) {
    if (!confirm(t('ai.confirm_archive', '确定要归档这个对话吗？'))) return;
    return apiSend('/api/v1/ai/conversations/' + convId, 'DELETE')
      .then(function () {
        state.conversations = state.conversations.filter(function (c) { return c.id !== convId; });
        if (state.activeId === convId) {
          state.activeId = null;
          state.messages = [];
          titleEl.textContent = t('ai.no_conv_selected', '未选择对话');
          actionsEl.hidden = true;
          renderEmptyStream();
        }
        renderConvList();
      })
      .catch(function (err) {
        showBanner('err', t('ai.error_archive', '归档失败：') + err.message);
      });
  }

  function renameActiveConv() {
    if (!state.activeId) return;
    var conv = state.conversations.find(function (c) { return c.id === state.activeId; });
    var newTitle = prompt(t('ai.rename_prompt', '新标题：'), conv ? conv.title : '');
    if (newTitle == null) return;
    newTitle = newTitle.trim();
    return apiSend('/api/v1/ai/conversations/' + state.activeId, 'PATCH', { title: newTitle })
      .then(function (updated) {
        if (conv) conv.title = updated.title;
        titleEl.textContent = updated.title || t('ai.untitled', '未命名对话');
        renderConvList();
      })
      .catch(function (err) {
        showBanner('err', t('ai.error_rename', '重命名失败：') + err.message);
      });
  }

  // ────────────── banner ──────────────

  function showBanner(level, msg) {
    var old = streamEl.parentNode.querySelector('.err-banner');
    if (old) old.remove();
    var cls = level === 'warn' ? 'err-banner warn' : (level === 'info' ? 'err-banner info' : 'err-banner');
    var banner = el('div', { class: cls, text: msg });
    streamEl.parentNode.insertBefore(banner, streamEl);
    if (level !== 'err') {
      setTimeout(function () { if (banner.parentNode) banner.remove(); }, 5000);
    }
  }

  // ────────────── textarea auto-resize ──────────────

  function autoResize() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
  }

  // ────────────── 事件 ──────────────

  newBtn.addEventListener('click', function () { newConversation(); });
  sendBtn.addEventListener('click', function () { sendMessage(); });
  renameBtn.addEventListener('click', function () { renameActiveConv(); });
  archiveBtn.addEventListener('click', function () { archiveConv(state.activeId); });
  inputEl.addEventListener('input', autoResize);
  inputEl.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      sendMessage();
    }
  });

  // i18n 语言切换时重渲染依赖文案的字段
  document.addEventListener('i18n:change', function () {
    if (state.activeId) openConversation(state.activeId);
    else { titleEl.textContent = t('ai.no_conv_selected', '未选择对话'); renderEmptyStream(); }
    sendBtn.textContent = state.sending ? t('ai.sending', '发送中…') : t('ai.send', '发送');
    if (state.health) renderQuota(state.health);
  });

  // boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
