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
    state.messages.forEach(function (m) {
      if (m.role === 'user') {
        streamEl.appendChild(renderUserMsg(m));
      } else if (m.role === 'assistant') {
        streamEl.appendChild(renderAssistantMsg(m));
        if (m.tool_name) toolCount++;
      } else if (m.role === 'tool') {
        // tool 消息：以「折叠的 tool 块」附加在主区
        // （主显示是「assistant text 块」+ 右侧 tool trace）
        // 已在 tool trace 中渲染，这里不重复
      }
    });
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
      bubble.innerHTML = '<span class="spinner"></span> ' + escapeHtml(t('ai.calling_tool', '正在调用工具：')) + ' <code>' + escapeHtml(m.tool_name) + '</code>…';
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
    item.appendChild(el('div', { class: 'name', text: m.tool_name || '?' }));
    if (m.tool_input) {
      var inputStr = typeof m.tool_input === 'string' ? m.tool_input : JSON.stringify(m.tool_input);
      item.appendChild(el('div', { class: 'input-preview', text: inputStr.length > 100 ? inputStr.slice(0, 100) + '…' : inputStr }));
    }
    if (m.content) {
      var summary = m.content.length > 200 ? m.content.slice(0, 200) + '…' : m.content;
      item.appendChild(el('div', { class: 'summary', text: summary }));
    }
    if (m.role === 'tool' && m.tool_call_id) {
      item.title = 'tool_call_id: ' + m.tool_call_id;
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
