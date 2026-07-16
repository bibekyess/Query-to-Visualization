// Chatbot client: streams /chat SSE events, renders markdown with inline citation
// chips, embeds visualizations, and shows a sources panel.

const state = {
  history: [],       // [{role, content}] neutral turns for the backend
  streaming: false,
};

// ── DOM helpers ──────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const messagesEl = () => $('messages');

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function scrollToBottom() {
  const el = messagesEl();
  el.scrollTop = el.scrollHeight;
}

// ── Minimal, safe Markdown → HTML ────────────────────────────
// Escapes first, then applies a small subset (headings, bold, italics, code,
// lists, paragraphs). Citation chips [n] are injected in a later pass.
function renderMarkdown(md) {
  const lines = escapeHtml(md).split('\n');
  let html = '';
  let inList = null;      // 'ul' | 'ol' | null
  let para = [];

  const flushPara = () => {
    if (para.length) { html += `<p>${inline(para.join(' '))}</p>`; para = []; }
  };
  const closeList = () => { if (inList) { html += `</${inList}>`; inList = null; } };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); closeList(); continue; }

    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { flushPara(); closeList(); const lvl = h[1].length; html += `<h${lvl}>${inline(h[2])}</h${lvl}>`; continue; }

    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ol) { flushPara(); if (inList !== 'ol') { closeList(); html += '<ol>'; inList = 'ol'; } html += `<li>${inline(ol[1])}</li>`; continue; }
    if (ul) { flushPara(); if (inList !== 'ul') { closeList(); html += '<ul>'; inList = 'ul'; } html += `<li>${inline(ul[1])}</li>`; continue; }

    closeList();
    para.push(line.trim());
  }
  flushPara(); closeList();
  return html;
}

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
}

// Replace [n] and [n][m] with clickable chips linked to the sources map.
function injectCitations(html, sourceByIndex) {
  return html.replace(/\[(\d+)\]/g, (match, n) => {
    const src = sourceByIndex[n];
    if (!src) return match;
    return `<a class="cite-chip" href="${src.url}" target="_blank" rel="noopener" title="${escapeHtml(src.title || '')}" data-src="${n}">${n}</a>`;
  });
}

// ── Message construction ─────────────────────────────────────
function addUserMessage(text) {
  const el = messagesEl();
  const div = document.createElement('div');
  div.className = 'msg user';
  div.innerHTML = `
    <div class="msg-avatar">🧑</div>
    <div class="msg-body">
      <div class="msg-role">You</div>
      <div class="msg-content">${renderMarkdown(text)}</div>
    </div>`;
  el.appendChild(div);
  scrollToBottom();
}

// Builds an assistant message shell and returns handles for streaming updates.
function addAssistantMessage() {
  const el = messagesEl();
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `
    <div class="msg-avatar">✦</div>
    <div class="msg-body">
      <div class="msg-role">Cheira</div>
      <div class="msg-tools"></div>
      <div class="msg-content"></div>
      <div class="msg-viz"></div>
      <div class="msg-sources"></div>
    </div>`;
  el.appendChild(div);
  scrollToBottom();
  return {
    tools: div.querySelector('.msg-tools'),
    content: div.querySelector('.msg-content'),
    viz: div.querySelector('.msg-viz'),
    sources: div.querySelector('.msg-sources'),
  };
}

// ── Send / stream ────────────────────────────────────────────
async function sendMessage(event) {
  if (event) event.preventDefault();
  if (state.streaming) return false;

  const input = $('input');
  const text = input.value.trim();
  if (!text) return false;

  $('welcome')?.remove();
  input.value = '';
  autoGrow(input);
  addUserMessage(text);

  const ui = addAssistantMessage();
  state.streaming = true;
  setSendEnabled(false);

  let rawText = '';
  let sourceByIndex = {};
  let allSources = [];
  const activePills = {};   // tool name → pill element

  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: state.history }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const rerender = () => {
      const html = injectCitations(renderMarkdown(rawText), sourceByIndex);
      ui.content.innerHTML = html + (state.streaming ? '<span class="stream-cursor"></span>' : '');
      wireCiteChips(ui.content, ui.sources);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const chunks = buffer.split('\n\n');
      buffer = chunks.pop();  // keep the trailing partial

      for (const chunk of chunks) {
        const line = chunk.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }

        if (ev.type === 'token') {
          rawText += ev.text;
          rerender();
          scrollToBottom();
        } else if (ev.type === 'tool_start') {
          if (!activePills[ev.tool]) {
            const pill = document.createElement('div');
            pill.className = 'tool-activity';
            pill.innerHTML = `<span class="tool-spinner"></span><span>${escapeHtml(ev.label)}…</span>`;
            ui.tools.appendChild(pill);
            activePills[ev.tool] = pill;
          }
          scrollToBottom();
        } else if (ev.type === 'sources') {
          allSources = ev.sources;
          sourceByIndex = {};
          for (const s of ev.sources) sourceByIndex[s.index] = s;
          renderSources(ui.sources, allSources);
          rerender();
          // Mark tool pills done as their results arrive.
          Object.values(activePills).forEach(markPillDone);
        } else if (ev.type === 'visualization') {
          const card = document.createElement('div');
          ui.viz.appendChild(card);
          markPillDone(activePills['create_visualization']);
          VizRenderer.render(card, ev.payload.response ?? ev.payload).then(scrollToBottom);
        } else if (ev.type === 'error') {
          ui.content.innerHTML += `<div class="err">⚠ ${escapeHtml(ev.message)}</div>`;
        } else if (ev.type === 'done') {
          Object.values(activePills).forEach(markPillDone);
        }
      }
    }

    // Finalize
    state.streaming = false;
    rerender();
    state.history.push({ role: 'user', content: text });
    state.history.push({ role: 'assistant', content: rawText });
  } catch (e) {
    state.streaming = false;
    ui.content.innerHTML += `<div class="err">⚠ ${escapeHtml(e.message)}</div>`;
  } finally {
    state.streaming = false;
    setSendEnabled(true);
    $('input').focus();
  }
  return false;
}

function markPillDone(pill) {
  if (!pill || pill.classList.contains('done')) return;
  pill.classList.add('done');
  const label = pill.querySelector('span:last-child').textContent.replace(/…$/, '');
  pill.innerHTML = `<span class="tool-check">✓</span><span>${escapeHtml(label)}</span>`;
}

function renderSources(container, sources) {
  if (!sources.length) { container.innerHTML = ''; return; }
  const cards = sources.map((s) => {
    const meta = s.type === 'pubmed'
      ? `${escapeHtml((s.authors || []).join(', '))}${s.authors?.length ? ' · ' : ''}${escapeHtml(s.journal || '')}${s.year ? ' · ' + escapeHtml(s.year) : ''}`
      : `${escapeHtml(s.id || '')}${s.status ? ' · ' + escapeHtml(s.status) : ''}${s.phase ? ' · ' + escapeHtml(s.phase) : ''}`;
    const typeLabel = s.type === 'pubmed' ? 'PubMed' : 'Clinical Trial';
    return `
      <a class="source-card" id="src-${s.index}" href="${s.url}" target="_blank" rel="noopener">
        <div class="source-num">${s.index}</div>
        <div class="source-main">
          <div class="source-type">${typeLabel}</div>
          <div class="source-title">${escapeHtml(s.title || s.id)}</div>
          <div class="source-meta">${meta}</div>
        </div>
      </a>`;
  }).join('');
  container.innerHTML = `<div class="sources"><div class="sources-label">Sources</div>${cards}</div>`;
}

// Clicking a citation chip scrolls to and flashes its source card.
function wireCiteChips(contentEl, sourcesEl) {
  contentEl.querySelectorAll('.cite-chip').forEach((chip) => {
    chip.onclick = (e) => {
      const n = chip.getAttribute('data-src');
      const card = sourcesEl.querySelector(`#src-${n}`);
      if (card) {
        e.preventDefault();
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.remove('flash');
        void card.offsetWidth;  // reflow to restart the animation
        card.classList.add('flash');
      }
    };
  });
}

// ── Composer UX ──────────────────────────────────────────────
function setSendEnabled(enabled) { $('send-btn').disabled = !enabled; }

function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function askSuggestion(btn) {
  $('input').value = btn.textContent.trim();
  autoGrow($('input'));
  sendMessage();
}

function newChat() {
  state.history = [];
  state.streaming = false;
  messagesEl().innerHTML = `
    <div class="welcome" id="welcome">
      <div class="welcome-mark">✦</div>
      <h1>How can I help with your research?</h1>
      <p>Ask about diseases, drugs, and treatments — I cite peer-reviewed literature and clinical-trial records, and draw live charts from ClinicalTrials.gov when the data tells the story.</p>
    </div>`;
  $('input').focus();
}

document.addEventListener('DOMContentLoaded', () => {
  const input = $('input');
  input.addEventListener('input', () => autoGrow(input));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
});
