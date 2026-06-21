/* ── State ─────────────────────────────────────────────────────────────────── */
const state = {
  token:       null,
  repId:       null,
  repName:     null,
  sessionId:   null,
  customerId:  null,
  history:     [],      // [{role, content}] — short-term memory owned by frontend
  streaming:   false,
};

const API = "";

/* ── DOM refs ──────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

/* ── Markdown renderer (simple, no dependency) ─────────────────────────────── */
function renderMarkdown(text) {
  return text
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,  '<h2>$1</h2>')
    .replace(/^# (.+)$/gm,   '<h1>$1</h1>')
    // Bold / italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,     '<em>$1</em>')
    // Code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Horizontal rule
    .replace(/^---$/gm, '<hr>')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // Tables (simple: | a | b | → table)
    .replace(/(\|.+\|\n)((\|[-:| ]+\|\n))((\|.+\|\n?)+)/gm, (match) => {
      const rows = match.trim().split('\n').filter(r => r.trim() && !r.match(/^\|[-:| ]+\|$/));
      const html = rows.map((row, i) => {
        const cells = row.split('|').slice(1, -1).map(c => c.trim());
        const tag   = i === 0 ? 'th' : 'td';
        return '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
      }).join('');
      return `<table>${html}</table>`;
    })
    // Unordered list
    .replace(/^[*-] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
    // Ordered list
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Paragraph (double newline)
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[a-z])(.+)$/gm, (m, p) => p ? p : '')
    // Line breaks
    .replace(/\n/g, '<br>');
}

function fmtMoney(n) {
  if (!n) return '—';
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1) + ' tỷ VND';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + ' triệu VND';
  return n.toLocaleString('vi-VN') + ' VND';
}

function fmtDate(d) {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('vi-VN');
}

/* ── Auth ──────────────────────────────────────────────────────────────────── */
$('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn   = $('btn-login');
  const errEl = $('login-error');
  errEl.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Đang đăng nhập...';

  try {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rep_id:   $('input-rep-id').value.trim(),
        password: $('input-password').value,
      }),
    });

    if (!res.ok) throw new Error('Sai thông tin đăng nhập');

    const data = await res.json();
    state.token   = data.access_token;
    state.repId   = data.rep_id;
    state.repName = data.full_name;

    $('rep-name').textContent = `${data.rep_id} — ${data.full_name}`;
    $('login-screen').style.display = 'none';
    $('app').classList.add('visible');
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Đăng nhập';
  }
});

/* ── Logout ────────────────────────────────────────────────────────────────── */
$('btn-logout').addEventListener('click', async () => {
  await endCurrentSession();
  Object.assign(state, { token: null, repId: null, repName: null,
    sessionId: null, customerId: null, history: [], streaming: false });
  $('app').classList.remove('visible');
  $('login-screen').style.display = '';
  $('chat-messages').innerHTML = '';
  $('c360-panel').innerHTML = emptyC360();
  $('customer-input').value = '';
  $('session-badge').style.display = 'none';
});

/* ── Session helpers ───────────────────────────────────────────────────────── */
async function endCurrentSession() {
  if (!state.sessionId || !state.customerId) return;
  try {
    await fetch(`${API}/sessions/end`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        session_id:  state.sessionId,
        customer_id: state.customerId,
        messages:    state.history,
      }),
    });
  } catch (_) {}
  state.sessionId  = null;
  state.customerId = null;
  state.history    = [];
}

function authHeaders() {
  return {
    'Content-Type':  'application/json',
    'Authorization': `Bearer ${state.token}`,
  };
}

/* ── Load customer ─────────────────────────────────────────────────────────── */
$('btn-load').addEventListener('click', loadCustomer);
$('customer-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadCustomer();
});

async function loadCustomer() {
  const cid = $('customer-input').value.trim().toUpperCase();
  if (!cid) return;

  const btn = $('btn-load');
  btn.disabled = true;
  btn.textContent = '...';

  // End previous session if any
  await endCurrentSession();

  try {
    // Start new session (pre-warms Redis)
    const sessRes = await fetch(`${API}/sessions/start`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ customer_id: cid }),
    });
    if (!sessRes.ok) throw new Error('Không thể tạo phiên làm việc');
    const sessData = await sessRes.json();
    state.sessionId  = sessData.session_id;
    state.customerId = cid;
    state.history    = [];

    // Load customer 360 for right panel
    const c360Res = await fetch(`${API}/customer/${cid}`, {
      headers: { 'Authorization': `Bearer ${state.token}` },
    });
    if (!c360Res.ok) throw new Error('Khách hàng không tồn tại hoặc không thuộc portfolio của bạn');
    const c360 = await c360Res.json();

    renderC360(c360);

    // Clear chat and show session badge
    $('chat-messages').innerHTML = '';
    $('session-badge').style.display = 'inline-block';
    $('session-badge').textContent = `Session: ${state.sessionId.split('-').slice(-1)[0]}`;

    appendSystemMsg(`Đã tải hồ sơ khách hàng ${c360.full_name}. Bạn có thể bắt đầu đặt câu hỏi.`);
    setInputEnabled(true);
    $('chat-textarea').focus();
  } catch (err) {
    appendSystemMsg(`⚠️ ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Tải';
  }
}

/* ── Send message ──────────────────────────────────────────────────────────── */
$('chat-textarea').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

$('btn-send').addEventListener('click', sendMessage);

async function sendMessage() {
  const textarea = $('chat-textarea');
  const message  = textarea.value.trim();
  if (!message || state.streaming) return;
  if (!state.sessionId) {
    appendSystemMsg('⚠️ Vui lòng tải hồ sơ khách hàng trước khi đặt câu hỏi.', true);
    return;
  }

  textarea.value = '';
  textarea.style.height = 'auto';
  state.streaming = true;
  setInputEnabled(false);

  // Rep bubble
  appendRepMessage(message);

  // Start agent bubble
  const agentEl = appendAgentMessage();

  try {
    await streamChat(message, agentEl);

    // Save turn to short-term history
    const finalAnswer = agentEl.querySelector('.bubble').innerText;
    state.history.push({ role: 'rep',   content: message });
    state.history.push({ role: 'agent', content: finalAnswer });

    // Keep last 20 turns (10 exchanges)
    if (state.history.length > 20) state.history = state.history.slice(-20);

  } catch (err) {
    const bubble = agentEl.querySelector('.bubble');
    bubble.innerHTML = `<span style="color:var(--tcb-red)">⚠️ Lỗi: ${err.message}</span>`;
    agentEl.querySelector('.verdict').className = 'verdict warn';
    agentEl.querySelector('.verdict').textContent = '⚠ Lỗi';
  } finally {
    state.streaming = false;
    setInputEnabled(true);
    $('chat-textarea').focus();
  }
}

/* ── SSE streaming ─────────────────────────────────────────────────────────── */
async function streamChat(message, agentEl) {
  const thinkEl   = agentEl.querySelector('.msg-thinking');
  const badgesEl  = agentEl.querySelector('.agent-badges');
  const bubbleEl  = agentEl.querySelector('.bubble');
  const verdictEl = agentEl.querySelector('.verdict');

  let fullText = '';
  let streamStarted = false;

  const res = await fetch(`${API}/chat`, {
    method:  'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      customer_id:          state.customerId,
      message,
      session_id:           state.sessionId,
      conversation_history: state.history,
    }),
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let   buffer  = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();  // keep incomplete line

    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      let ev;
      try { ev = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }

      switch (ev.event) {

        case 'thinking':
          thinkEl.style.display = 'flex';
          thinkEl.querySelector('span').textContent = ev.data;
          scrollChat();
          break;

        case 'agent_result': {
          const r = JSON.parse(ev.data);
          const badge = document.createElement('span');
          badge.className = `agent-badge ${r.verified ? 'verified' : 'unverified'}`;
          badge.textContent = `${r.verified ? '✓' : '⚠'} ${r.agent}`;
          badge.title = r.warning || '';
          badgesEl.appendChild(badge);
          scrollChat();
          break;
        }

        case 'token':
          thinkEl.style.display = 'none';
          if (!streamStarted) {
            streamStarted = true;
            bubbleEl.classList.add('streaming-cursor');
          }
          fullText += ev.data;
          bubbleEl.innerHTML = renderMarkdown(fullText);
          scrollChat();
          break;

        case 'done': {
          bubbleEl.classList.remove('streaming-cursor');
          bubbleEl.innerHTML = renderMarkdown(fullText);
          let meta = {};
          try { meta = JSON.parse(ev.data); } catch (_) {}
          if (meta.verified === false) {
            verdictEl.className = 'verdict warn';
            verdictEl.innerHTML = `⚠ ${meta.warning || 'Cần kiểm tra lại'}`;
          } else {
            verdictEl.className = 'verdict ok';
            verdictEl.textContent = '✓ Đã xác minh';
          }
          scrollChat();
          break;
        }

        case 'error':
          thinkEl.style.display = 'none';
          bubbleEl.classList.remove('streaming-cursor');
          bubbleEl.innerHTML = `<span style="color:var(--tcb-red)">⚠️ ${ev.data}</span>`;
          verdictEl.className = 'verdict warn';
          verdictEl.textContent = '⚠ Bị chặn';
          scrollChat();
          break;
      }
    }
  }
}

/* ── Message builders ──────────────────────────────────────────────────────── */
function appendRepMessage(text) {
  const el = document.createElement('div');
  el.className = 'msg-rep';
  el.innerHTML = `<div class="bubble">${text}</div>`;
  $('chat-messages').appendChild(el);
  scrollChat();
}

function appendAgentMessage() {
  const el = document.createElement('div');
  el.className = 'msg-agent';
  el.innerHTML = `
    <div class="agent-badges"></div>
    <div class="msg-thinking" style="display:none">
      <div class="spinner"></div>
      <span>Đang xử lý...</span>
    </div>
    <div class="bubble"></div>
    <div class="verdict pending">⏳ Đang xác minh...</div>`;
  $('chat-messages').appendChild(el);
  scrollChat();
  return el;
}

function appendSystemMsg(text, isError = false) {
  const el = document.createElement('div');
  el.style.cssText = `text-align:center;font-size:12px;color:${isError ? 'var(--tcb-red)' : 'var(--text-muted)'};padding:6px 0;`;
  el.textContent = text;
  $('chat-messages').appendChild(el);
  scrollChat();
}

function scrollChat() {
  const el = $('chat-messages');
  el.scrollTop = el.scrollHeight;
}

function setInputEnabled(enabled) {
  $('chat-textarea').disabled = !enabled;
  $('btn-send').disabled     = !enabled;
}

/* ── Customer 360 renderer ─────────────────────────────────────────────────── */
function emptyC360() {
  return `<div class="c360-empty">
    <div class="icon">👤</div>
    <p>Nhập mã khách hàng và nhấn <strong>Tải</strong> để xem hồ sơ</p>
  </div>`;
}

function renderC360(c) {
  const products = (c.products_held || []).map(p =>
    `<span class="product-chip">${typeof p === 'string' ? p : p.product_code}</span>`).join('');

  const contracts = (c.contracts || []).slice(0, 5).map(ct => {
    const statusClass = `status-${ct.status}`;
    const amount = ct.key_amount ? `<br><small>${fmtMoney(ct.key_amount)}</small>` : '';
    return `<div class="contract-item">
      <div class="contract-header">
        <span class="contract-name">${ct.product_name}</span>
        <span class="contract-status ${statusClass}">${ct.status}</span>
      </div>
      <div class="contract-meta">
        ${ct.contract_id} · ${fmtDate(ct.start_date)} – ${fmtDate(ct.end_date)}${amount}
      </div>
    </div>`;
  }).join('');

  const txns = (c.recent_transactions || []).slice(0, 8).map(t => {
    const isCredit = t.amount > 0;
    return `<div class="txn-item">
      <div class="txn-desc">
        <div class="txn-name">${t.merchant_name || t.description || t.type}</div>
        <div class="txn-date">${fmtDate(t.transaction_date)} · ${t.merchant_category || ''}</div>
      </div>
      <div class="txn-amount ${isCredit ? 'credit' : 'debit'}">
        ${isCredit ? '+' : ''}${fmtMoney(t.amount)}
      </div>
    </div>`;
  }).join('');

  const score = c.credit_score || 0;
  const scorePct = Math.min(100, Math.round((score / 850) * 100));

  $('c360-panel').innerHTML = `
    <div class="c360-header">
      <div>
        <div class="c360-name">${c.full_name || '—'}</div>
        <div class="c360-id">${c.customer_id} · ${c.city || ''}</div>
        <div class="badges">
          <span class="badge badge-segment-${c.segment}">${c.segment || '—'}</span>
          <span class="badge badge-kyc-${c.kyc_status}">${c.kyc_status || '—'}</span>
        </div>
      </div>
      <div style="text-align:right;font-size:12px;color:var(--text-muted)">
        <div>Nghề nghiệp</div>
        <div style="font-weight:600;color:var(--text)">${c.occupation || '—'}</div>
        <div style="margin-top:6px">Khách hàng từ</div>
        <div style="font-weight:600;color:var(--text)">${fmtDate(c.relationship_since)}</div>
      </div>
    </div>

    <div class="c360-card">
      <div class="card-title">📊 Thông tin</div>
      <div class="info-grid">
        <div class="info-item">
          <label>Thu nhập</label>
          <span>${c.income_range || '—'}</span>
        </div>
        <div class="info-item">
          <label>Điểm tích lũy</label>
          <span>${(c.loyalty_points || 0).toLocaleString('vi-VN')}</span>
        </div>
        <div class="info-item" style="grid-column:span 2">
          <label>Credit score — ${score}</label>
          <div class="score-bar">
            <div class="score-fill" style="width:${scorePct}%"></div>
          </div>
        </div>
      </div>
    </div>

    ${products ? `<div class="c360-card">
      <div class="card-title">💳 Sản phẩm (${(c.products_held||[]).length})</div>
      <div class="products-grid">${products}</div>
    </div>` : ''}

    ${contracts ? `<div class="c360-card">
      <div class="card-title">📋 Hợp đồng (${(c.contracts||[]).length})</div>
      ${contracts}
    </div>` : ''}

    ${txns ? `<div class="c360-card">
      <div class="card-title">💰 Giao dịch gần nhất</div>
      <div class="txn-list">${txns}</div>
    </div>` : ''}`;

  // Enable end-session button if exists
  if ($('btn-end-session')) $('btn-end-session').style.display = 'inline-block';
}

/* ── Init ──────────────────────────────────────────────────────────────────── */
$('c360-panel').innerHTML = emptyC360();

// Auto-resize textarea
$('chat-textarea').addEventListener('input', function () {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// End session on page close
window.addEventListener('beforeunload', () => endCurrentSession());
