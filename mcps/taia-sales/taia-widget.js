(function () {
  'use strict';

  // ── Configuration ─────────────────────────────────────────────────────
  var MIN_INDICATOR_MS = 1200;
  var MIN_TYPE_MS = 1800;
  var WORD_DELAY = 30;
  var LIST_DELAY = 90;
  var BLOCK_PAUSE = 120;

  var scripts = document.getElementsByTagName('script');
  var currentScript = scripts[scripts.length - 1];
  var API_URL = currentScript.getAttribute('data-api-url') || '/chat/stream';

  var isOpen = false, isSending = false, messages = [];
  var panelCreated = false;

  // ── Helpers ───────────────────────────────────────────────────────────
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function normalizeCurrency(t) { return t.replace(/\u20B1/g, '$').replace(/\bPHP\b/gi, 'USD').replace(/\bpesos?\b/gi, 'dollars'); }

  function inlineFormat(s) {
    var out = escapeHtml(s);
    out = out.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');
    out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    return out;
  }

  function renderLight(text) { return inlineFormat(text).replace(/\n/g, '<br>'); }

  function renderMarkdown(text) {
    if (!text) return '';
    text = text.replace(/\r\n/g, '\n');
    var lines = text.split('\n'), out = [], i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (line.trim().indexOf('```') === 0) {
        var lang = line.trim().slice(3).trim(), cl = [];
        i++;
        while (i < lines.length && lines[i].trim().indexOf('```') !== 0) { cl.push(lines[i]); i++; }
        if (i < lines.length) i++;
        out.push('<div class="code-block"><div class="code-block-header">' + (lang || 'output') + '</div><pre class="code-block-body">' + escapeHtml(cl.join('\n')) + '</pre></div>');
        continue;
      }
      var hM = line.match(/^(#{1,3})\s+(.+)/);
      if (hM) { out.push('<div class="md-h' + hM[1].length + '">' + inlineFormat(hM[2]) + '</div>'); i++; continue; }
      if (/^[\-\*]{3,}\s*$/.test(line.trim())) { out.push('<hr class="md-hr">'); i++; continue; }
      if (/^>\s?/.test(line)) {
        var bq = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) { bq.push(inlineFormat(lines[i].replace(/^>\s?/, ''))); i++; }
        out.push('<div class="md-blockquote">' + bq.join('<br>') + '</div>'); continue;
      }
      if (/^[\-\*]\s/.test(line)) {
        var ul = [];
        while (i < lines.length && /^[\-\*]\s/.test(lines[i])) { ul.push('<li>' + inlineFormat(lines[i].replace(/^[\-\*]\s/, '')) + '</li>'); i++; }
        out.push('<ul class="md-ul">' + ul.join('') + '</ul>'); continue;
      }
      if (/^\d+\.\s/.test(line)) {
        var ol = [];
        while (i < lines.length && /^\d+\.\s/.test(lines[i])) { ol.push('<li>' + inlineFormat(lines[i].replace(/^\d+\.\s/, '')) + '</li>'); i++; }
        out.push('<ol class="md-ol">' + ol.join('') + '</ol>'); continue;
      }
      if (line.trim() === '') { out.push('<br>'); i++; continue; }
      out.push('<span>' + inlineFormat(line) + '</span><br>'); i++;
    }
    var html = out.join('');
    html = html.replace(/(Order\s*#\s*\d+|ORD-\d+)/gi, function (m) {
      return '<span style="display:inline-flex;align-items:center;gap:.3rem;background:linear-gradient(135deg,var(--brand),var(--brand-dark));color:#000;padding:.15rem .5rem;border-radius:6px;font-size:.85em;font-weight:700;vertical-align:baseline;white-space:nowrap;margin:0 .15rem;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' + m + '</span>';
    });
    return html;
  }

  function parseBlocks(text) {
    var blocks = [], lines = text.split('\n'), i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (line.trim().indexOf('```') === 0) {
        var cl = []; i++;
        while (i < lines.length && lines[i].trim().indexOf('```') !== 0) { cl.push(lines[i]); i++; }
        if (i < lines.length) i++;
        blocks.push({ type: 'instant', text: '```\n' + cl.join('\n') + '\n```' }); continue;
      }
      if (/^#{1,3}\s/.test(line)) { blocks.push({ type: 'instant', text: line }); i++; continue; }
      if (/^[\-\*]{3,}\s*$/.test(line.trim())) { blocks.push({ type: 'instant', text: line }); i++; continue; }
      if (/^>\s?/.test(line)) {
        var bq = []; while (i < lines.length && /^>\s?/.test(lines[i])) { bq.push(lines[i]); i++; }
        blocks.push({ type: 'instant', text: bq.join('\n') }); continue;
      }
      if (/^[\-\*]\s/.test(line)) {
        var ul = []; while (i < lines.length && /^[\-\*]\s/.test(lines[i])) { ul.push(lines[i]); i++; }
        blocks.push({ type: 'list', items: ul }); continue;
      }
      if (/^\d+\.\s/.test(line)) {
        var ol = []; while (i < lines.length && /^\d+\.\s/.test(lines[i])) { ol.push(lines[i]); i++; }
        blocks.push({ type: 'list', items: ol }); continue;
      }
      if (line.trim() === '') { blocks.push({ type: 'empty' }); i++; continue; }
      var para = [];
      while (i < lines.length) {
        var c = lines[i];
        if (c.trim() === '' || c.trim().indexOf('```') === 0 || /^[\-\*]\s/.test(c) || /^\d+\.\s/.test(c) || /^#{1,3}\s/.test(c) || /^>\s?/.test(c) || /^[\-\*]{3,}\s*$/.test(c.trim())) break;
        para.push(c); i++;
      }
      if (para.length) blocks.push({ type: 'paragraph', text: para.join('\n') });
    }
    return blocks;
  }

  function typewriterFull(text, msgDiv) {
    return new Promise(function (resolve) {
      var blocks = parseBlocks(text), naturalMs = 0;
      for (var b = 0; b < blocks.length; b++) {
        if (blocks[b].type === 'paragraph') naturalMs += blocks[b].text.split(/\s+/).length * WORD_DELAY;
        else if (blocks[b].type === 'list') naturalMs += blocks[b].items.length * LIST_DELAY;
        else if (blocks[b].type === 'instant') naturalMs += BLOCK_PAUSE;
      }
      var scale = naturalMs > 0 ? Math.max(1, MIN_TYPE_MS / naturalMs) : 1;
      var wD = Math.round(WORD_DELAY * scale), lD = Math.round(LIST_DELAY * scale), bD = Math.round(BLOCK_PAUSE * scale);
      var blockIdx = 0, subIdx = 0, accumulated = '';
      function play() {
        if (blockIdx >= blocks.length) { msgDiv.innerHTML = renderMarkdown(text); scrollChat(); resolve(); return; }
        var block = blocks[blockIdx];
        if (block.type === 'instant') {
          accumulated += block.text + '\n'; msgDiv.innerHTML = renderMarkdown(accumulated); scrollChat();
          blockIdx++; setTimeout(play, bD);
        } else if (block.type === 'empty') { accumulated += '\n'; blockIdx++; play(); }
        else if (block.type === 'list') {
          if (subIdx < block.items.length) {
            accumulated += block.items[subIdx] + '\n'; msgDiv.innerHTML = renderMarkdown(accumulated); scrollChat();
            subIdx++; setTimeout(play, lD);
          } else { subIdx = 0; blockIdx++; play(); }
        } else if (block.type === 'paragraph') {
          var words = block.text.split(/(\s+)/);
          if (subIdx < words.length) {
            accumulated += words[subIdx]; subIdx++; msgDiv.innerHTML = renderLight(accumulated); scrollChat();
            setTimeout(play, wD);
          } else { msgDiv.innerHTML = renderMarkdown(accumulated); scrollChat(); subIdx = 0; blockIdx++; setTimeout(play, 50); }
        }
      }
      play();
    });
  }

  function parseResponse(rawBody) {
    if (rawBody.indexOf('data: ') !== -1) {
      var content = '', lines = rawBody.split('\n');
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (line.indexOf('data: ') !== 0) continue;
        var raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') continue;
        try { var j = JSON.parse(raw); if (j.choices && j.choices[0] && j.choices[0].delta && j.choices[0].delta.content) content += j.choices[0].delta.content; } catch (e) { }
      }
      if (content) return content;
    }
    try { var json = JSON.parse(rawBody); if (json.choices && json.choices[0] && json.choices[0].message) return json.choices[0].message.content || ''; } catch (e) { }
    return '';
  }

  // ── DOM references ─────────────────────────────────────────────────────
  var root, chatBtn, chatPanel, chatMessages, chatInput, chatSend;

  // ── CSS injection (TENSEI white/amber theme) ─────────────────────────
  function injectCSS() {
    if (document.getElementById('taia-widget-styles')) return;
    // Load fonts (clean sans-serif, no Orbitron needed for TENSEI)
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
    document.head.appendChild(link);

    var style = document.createElement('style');
    style.id = 'taia-widget-styles';
    style.textContent = '\
#taia-widget-root{--brand:#F59E0B;--brand-dark:#D97706;--surface:#FFFFFF;--surface2:#F9FAFB;--surface3:#E5E7EB;--text:#111827;--muted:#6B7280;--radius:12px;--chat-w:720px;--chat-h:600px;font-family:"Inter","Segoe UI",system-ui,sans-serif;line-height:1.6;color:var(--text)}\
#taia-widget-root *,#taia-widget-root *::before,#taia-widget-root *::after{box-sizing:border-box}\
#taia-widget-root #chat-btn{position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;width:60px;height:60px;border-radius:50%;background:var(--brand);box-shadow:0 4px 20px rgba(245,158,11,.4),0 0 40px rgba(245,158,11,.12);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s,transform .2s}\
#taia-widget-root #chat-btn:hover{background:var(--brand-dark);transform:scale(1.07)}\
#taia-widget-root #chat-btn svg{width:26px;height:26px;fill:#fff}\
#taia-widget-root #chat-panel{position:fixed;bottom:5.5rem;right:1.5rem;z-index:9998;width:min(var(--chat-w),calc(100vw - 3rem));height:var(--chat-h);background:var(--surface);border:1px solid var(--surface3);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.1);overflow:hidden;display:none;flex-direction:column;transform:translateY(20px) scale(.97);opacity:0;transition:transform .25s,opacity .2s}\
#taia-widget-root #chat-panel.open{display:flex;transform:translateY(0) scale(1);opacity:1}\
#taia-widget-root .chat-header{display:flex;align-items:center;gap:.75rem;padding:1rem 1.25rem;background:var(--surface2);border-bottom:1px solid var(--surface3)}\
#taia-widget-root .chat-avatar{width:36px;height:36px;border-radius:50%;background:var(--brand);display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;color:#fff}\
#taia-widget-root .chat-header-info h4{font-size:.9rem;color:var(--text);font-weight:700}\
#taia-widget-root .chat-header-info span{font-size:.72rem;color:var(--brand);display:flex;align-items:center;gap:.3rem}\
#taia-widget-root .chat-header-info span::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--brand);display:inline-block;animation:taiaBlink 1.5s ease-in-out infinite}\
#taia-widget-root .chat-actions{margin-left:auto;display:flex;gap:.5rem}\
#taia-widget-root .chat-header-btn{background:none;border:1px solid var(--surface3);border-radius:4px;color:var(--muted);cursor:pointer;font-size:.8rem;padding:.25rem .5rem;transition:all .2s}\
#taia-widget-root .chat-header-btn:hover{background:var(--surface2);color:var(--text);border-color:var(--brand)}\
#taia-widget-root .chat-messages{flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.75rem;background:var(--surface)}\
#taia-widget-root .chat-messages::-webkit-scrollbar{width:4px}\
#taia-widget-root .chat-messages::-webkit-scrollbar-thumb{background:rgba(0,0,0,.1);border-radius:2px}\
#taia-widget-root .msg{max-width:85%;padding:.65rem .9rem;border-radius:12px;font-size:.88rem;line-height:1.5;white-space:pre-wrap;word-break:break-word}\
#taia-widget-root .msg.bot{background:var(--surface2);align-self:flex-start;border-bottom-left-radius:4px;color:var(--text)}\
#taia-widget-root .msg.user{background:var(--brand);color:#fff;font-weight:500;align-self:flex-end;border-bottom-right-radius:4px}\
#taia-widget-root .msg.bot strong{color:var(--text);font-weight:700}\
#taia-widget-root .chat-input-row{display:flex;gap:.5rem;padding:.75rem 1rem;border-top:1px solid var(--surface3);background:var(--surface2)}\
#taia-widget-root #chat-input{flex:1;background:var(--surface);border:1px solid var(--surface3);border-radius:8px;padding:.6rem .9rem;color:var(--text);font-size:.88rem;outline:none;resize:none;font-family:inherit}\
#taia-widget-root #chat-input:focus{border-color:var(--brand)}\
#taia-widget-root #chat-send{background:var(--brand);border:none;border-radius:8px;color:#fff;padding:.6rem .9rem;cursor:pointer;transition:background .2s}\
#taia-widget-root #chat-send:hover{background:var(--brand-dark)}\
#taia-widget-root #chat-send:disabled{opacity:.5;cursor:not-allowed}\
#taia-widget-root #chat-send svg{width:18px;height:18px;fill:#fff}\
#taia-widget-root .typing-indicator{display:flex;gap:5px;padding:.6rem .2rem;align-items:center}\
#taia-widget-root .typing-indicator span{width:7px;height:7px;border-radius:50%;background:var(--brand);opacity:.3;animation:taiaTypeBounce 1.4s ease-in-out infinite}\
#taia-widget-root .typing-indicator span:nth-child(2){animation-delay:.16s}\
#taia-widget-root .typing-indicator span:nth-child(3){animation-delay:.32s}\
#taia-widget-root .code-block{background:var(--surface2);border:1px solid var(--surface3);border-radius:10px;overflow:hidden;margin:.75rem 0}\
#taia-widget-root .code-block-header{background:var(--surface3);padding:.4rem .85rem;font-family:monospace;font-size:.58rem;color:var(--muted);letter-spacing:.06em;border-bottom:1px solid rgba(0,0,0,.05);text-transform:uppercase}\
#taia-widget-root .code-block-body{padding:.85rem 1rem;margin:0;font-family:monospace;font-size:.72rem;line-height:1.85;overflow-x:auto;white-space:pre-wrap;color:var(--text)}\
#taia-widget-root .inline-code{background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.2);padding:.1rem .38rem;border-radius:4px;font-size:.85em;color:var(--brand-dark);font-family:monospace}\
#taia-widget-root .md-blockquote{border-left:3px solid var(--brand);padding:.45rem .9rem;margin:.6rem 0;color:var(--muted);font-size:.88rem;background:rgba(245,158,11,.03);border-radius:0 8px 8px 0}\
#taia-widget-root .md-ul{margin:.5rem 0;padding-left:1.2rem}\
#taia-widget-root .md-ul li{margin-bottom:.25rem}\
#taia-widget-root .md-ol{margin:.5rem 0;padding-left:1.2rem}\
#taia-widget-root .md-ol li{margin-bottom:.25rem}\
#taia-widget-root .md-h1{font-size:1.15rem;font-weight:700;color:var(--text);margin:.85rem 0 .35rem}\
#taia-widget-root .md-h2{font-size:1.05rem;font-weight:700;color:var(--text);margin:.7rem 0 .3rem}\
#taia-widget-root .md-h3{font-size:.95rem;font-weight:700;color:var(--text);margin:.6rem 0 .25rem}\
#taia-widget-root .md-hr{height:1px;background:linear-gradient(90deg,transparent,rgba(245,158,11,.15),transparent);margin:.85rem 0;border:none}\
@keyframes taiaBlink{0%,100%{opacity:1}50%{opacity:.3}}\
@keyframes taiaTypeBounce{0%,60%,100%{transform:translateY(0);opacity:.3}30%{transform:translateY(-8px);opacity:1}}\
@media (max-width: 600px) {\
  #taia-widget-root #chat-panel{ width: 100vw; height: 100vh; bottom:0; right:0; border-radius:0; }\
  #taia-widget-root #chat-btn{ bottom:1rem; right:1rem; }\
}\
';
    document.head.appendChild(style);
  }

  // ── UI Creation ────────────────────────────────────────────────────────
  function initButton() {
    injectCSS();
    root = document.createElement('div');
    root.id = 'taia-widget-root';
    document.body.appendChild(root);
    chatBtn = document.createElement('button');
    chatBtn.id = 'chat-btn';
    chatBtn.type = 'button';
    chatBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>';
    chatBtn.addEventListener('click', function (e) { e.preventDefault(); toggleChat(); });
    root.appendChild(chatBtn);
  }

  function createPanel() {
    chatPanel = document.createElement('div');
    chatPanel.id = 'chat-panel';

    var header = document.createElement('div');
    header.className = 'chat-header';
    var avatarDiv = document.createElement('div');
    avatarDiv.className = 'chat-avatar';
    avatarDiv.textContent = '\uD83E\uDD16';
    var infoDiv = document.createElement('div');
    infoDiv.className = 'chat-header-info';
    infoDiv.innerHTML = '<h4>TAIA \u2014 Sales Assistant</h4><span>System Online</span>';
    var actionsDiv = document.createElement('div');
    actionsDiv.className = 'chat-actions';
    var resetBtn = document.createElement('button');
    resetBtn.className = 'chat-header-btn';
    resetBtn.type = 'button';
    resetBtn.textContent = '\u21BA Reset';
    resetBtn.addEventListener('click', function (e) { e.preventDefault(); resetChat(); });
    var closeBtn = document.createElement('button');
    closeBtn.className = 'chat-header-btn';
    closeBtn.type = 'button';
    closeBtn.textContent = '\u2715';
    closeBtn.addEventListener('click', function (e) { e.preventDefault(); closePanel(); });
    actionsDiv.appendChild(resetBtn);
    actionsDiv.appendChild(closeBtn);
    header.appendChild(avatarDiv);
    header.appendChild(infoDiv);
    header.appendChild(actionsDiv);
    chatPanel.appendChild(header);

    chatMessages = document.createElement('div');
    chatMessages.className = 'chat-messages';
    chatMessages.id = 'chat-messages';
    chatPanel.appendChild(chatMessages);

    var inputRow = document.createElement('div');
    inputRow.className = 'chat-input-row';
    chatInput = document.createElement('textarea');
    chatInput.id = 'chat-input';
    chatInput.rows = 1;
    chatInput.placeholder = 'Ask about products, pricing, or place an order...';
    chatInput.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    chatSend = document.createElement('button');
    chatSend.id = 'chat-send';
    chatSend.type = 'button';
    chatSend.innerHTML = '<svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>';
    chatSend.addEventListener('click', function (e) { e.preventDefault(); sendMessage(); });
    inputRow.appendChild(chatInput);
    inputRow.appendChild(chatSend);
    chatPanel.appendChild(inputRow);

    root.appendChild(chatPanel);
    panelCreated = true;
  }

  function toggleChat() {
    if (!panelCreated) {
      createPanel();
      addMessage('bot', 'Hello! I\'m **TAIA**, the TENSEI sales assistant.\n\nI can help you explore our services, answer questions, and more. How can I assist you today?');
    }
    isOpen = !isOpen;
    if (isOpen) { chatPanel.classList.add('open'); setTimeout(function () { chatInput.focus(); }, 300); }
    else { chatPanel.classList.remove('open'); }
  }
  function openPanel() { if (!isOpen) toggleChat(); }
  function closePanel() { if (isOpen) toggleChat(); }
  function resetChat() { messages = []; chatMessages.innerHTML = ''; addMessage('bot', 'Terminal reset. How can I assist you?'); }
  function scrollChat() { chatMessages.scrollTop = chatMessages.scrollHeight; }

  function addMessage(role, text) {
    var div = document.createElement('div');
    div.className = 'msg ' + role;
    if (role === 'bot') div.innerHTML = renderMarkdown(normalizeCurrency(text));
    else div.textContent = text;
    chatMessages.appendChild(div);
    scrollChat();
    return div;
  }

  function showTypingIndicator() {
    var div = document.createElement('div');
    div.className = 'msg bot';
    div.id = 'typing-indicator';
    div.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    chatMessages.appendChild(div);
    scrollChat();
  }

  function removeTypingIndicator() {
    var el = document.getElementById('typing-indicator');
    if (el) el.remove();
  }

  // ── Core send logic ────────────────────────────────────────────────────
  async function sendMessage() {
    if (isSending) return;
    var text = chatInput.value.trim();
    if (!text) return;
    messages.push({ role: 'user', content: text });
    chatInput.value = '';
    addMessage('user', text);
    isSending = true;
    chatSend.disabled = true;

    showTypingIndicator();
    var t0 = Date.now();

    try {
      var res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: messages })
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);

      var rawBody = '';
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      while (true) {
        var result = await reader.read();
        if (result.done) break;
        rawBody += decoder.decode(result.value, { stream: true });
      }

      var elapsed = Date.now() - t0;
      if (elapsed < MIN_INDICATOR_MS) await sleep(MIN_INDICATOR_MS - elapsed);

      var reply = normalizeCurrency(parseResponse(rawBody));
      if (!reply) {
        removeTypingIndicator();
        addMessage('bot', '\u26A0 No response received. Please try again.');
        messages.pop();
        return;
      }

      removeTypingIndicator();
      var msgDiv = document.createElement('div');
      msgDiv.className = 'msg bot';
      chatMessages.appendChild(msgDiv);
      await typewriterFull(reply, msgDiv);
      messages.push({ role: 'assistant', content: reply });

    } catch (e) {
      var errElapsed = Date.now() - t0;
      if (errElapsed < 600) await sleep(600 - errElapsed);
      removeTypingIndicator();
      addMessage('bot', '\u26A0 Connection error. Ensure the terminal is online.');
      messages.pop();
    } finally {
      isSending = false;
      chatSend.disabled = false;
      chatInput.focus();
    }
  }

  initButton();

  window.TaiaChatWidget = { open: openPanel, close: closePanel, toggle: toggleChat };
})();