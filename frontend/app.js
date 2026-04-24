const $ = (id) => document.getElementById(id);

function symbols() {
  return $('symbols').value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
}

function fmt(v, d = 4) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toFixed(d);
}

function log(title, obj) {
  const line = `[${new Date().toLocaleTimeString()}] ${title}\n${obj ? JSON.stringify(obj, null, 2) : ''}\n`;
  $('log').textContent = line + $('log').textContent;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

async function refreshStatus() {
  try {
    const data = await api('/api/status');
    $('statusBox').textContent = 'OK · DB ' + (data.db_time || '—');
    $('kpiCandles').textContent = data.candles ?? '—';
    $('kpiSentiment').textContent = data.sentiment_sources?.cryptopanic ? 'Free+CP' : 'Free';
  } catch (e) {
    $('statusBox').textContent = 'DB/API error';
    log('ERROR status: ' + e.message);
  }
}

async function refreshUniverse() {
  try {
    const mode = $('universeMode').value;
    const data = await api(`/api/symbols/universe/latest?category=${$('category').value}&mode=${mode}&limit=50`);
    const tbody = $('universeTable').querySelector('tbody');
    tbody.innerHTML = '';
    const items = data.items || [];
    $('kpiUniverse').textContent = items.length || '—';
    for (const r of items) {
      const comp = r.components || {};
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${r.rank_no}</td><td>${r.symbol}</td><td>${r.reason || '—'}</td><td>${fmt(r.liquidity_score, 3)}</td><td>${fmt(comp.spread_pct, 4)}</td><td>${fmt(comp.turnover_24h, 1)}</td><td>${fmt(comp.open_interest_value, 1)}</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) { log('Universe refresh error: ' + e.message); }
}

async function refreshSignals() {
  const data = await api('/api/signals/latest?limit=40');
  const tbody = $('signalsTable').querySelector('tbody');
  tbody.innerHTML = '';
  for (const s of data.signals || []) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${s.id}</td><td>${new Date(s.created_at).toLocaleString()}</td><td>${s.symbol}</td><td>${s.strategy}</td>
      <td><span class="pill ${s.direction}">${s.direction}</span></td><td>${fmt(s.confidence, 3)}</td>
      <td>${fmt(s.entry, 4)}</td><td>${fmt(s.stop_loss, 4)}</td><td>${fmt(s.take_profit, 4)}</td>
      <td><button class="small" data-signal="${s.id}">LLM</button></td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll('button[data-signal]').forEach(btn => {
    btn.onclick = async () => {
      try {
        $('briefBox').textContent = 'LLM думает...';
        const b = await api('/api/llm/brief', { method: 'POST', body: JSON.stringify({ signal_id: Number(btn.dataset.signal) }) });
        $('briefBox').textContent = b.brief;
      } catch (e) { $('briefBox').textContent = e.message; }
    };
  });
}

async function refreshRank() {
  try {
    const data = await api(`/api/research/rank?category=${$('category').value}&interval=${$('interval').value}&limit=30`);
    const tbody = $('rankTable').querySelector('tbody');
    tbody.innerHTML = '';
    for (const r of data.items || []) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${fmt(r.research_score, 3)}</td><td>${r.symbol}</td><td>${r.strategy}</td><td><span class="pill ${r.direction}">${r.direction}</span></td><td>${fmt(r.confidence, 3)}</td><td>${fmt(r.profit_factor, 2)}</td><td>${fmt(r.sharpe, 2)}</td><td>${fmt(r.max_drawdown, 3)}</td><td>${fmt(r.roc_auc, 3)}</td><td>${fmt(r.spread_pct, 4)}</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) { log('Rank error: ' + e.message); }
}

function drawEquity(curve) {
  const canvas = $('equityCanvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#10151f';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!curve || curve.length < 2) return;
  const vals = curve.map(p => Number(p.equity));
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = 24;
  ctx.strokeStyle = '#2f3b52';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = pad + i * (canvas.height - pad * 2) / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(canvas.width - pad, y); ctx.stroke();
  }
  ctx.strokeStyle = '#8dd5ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = pad + i * (canvas.width - pad * 2) / (vals.length - 1);
    const y = canvas.height - pad - ((v - min) / Math.max(max - min, 1e-9)) * (canvas.height - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#cfe6ff';
  ctx.fillText(`min ${fmt(min, 2)} · max ${fmt(max, 2)}`, pad, 18);
}

async function refreshEquity() {
  const data = await api('/api/equity/latest?limit=1');
  if (data.runs && data.runs[0]) drawEquity(data.runs[0].equity_curve);
}

async function refreshNews() {
  const sym = symbols()[0] || 'BTCUSDT';
  const data = await api(`/api/news/latest?symbol=${sym}&limit=12`);
  const list = $('newsList');
  list.innerHTML = '';
  for (const n of data.news || []) {
    const div = document.createElement('div');
    div.className = 'news-item';
    div.innerHTML = `<b>${n.symbol}</b> <span>${n.source}</span><p>${n.title}</p><small>${n.published_at ? new Date(n.published_at).toLocaleString() : ''} · score ${fmt(n.llm_score ?? n.sentiment_score, 3)}</small>`;
    list.appendChild(div);
  }
  const s = await api(`/api/sentiment/summary?symbol=${sym}&limit=6`);
  $('sentimentBox').textContent = JSON.stringify(s.result, null, 2);
}

$('syncUniverseBtn').onclick = async () => {
  try {
    const data = await api('/api/symbols/universe/build', { method: 'POST', body: JSON.stringify({ category: $('category').value, mode: $('universeMode').value, limit: 25, refresh: true }) });
    $('symbols').value = (data.result.symbols || []).slice(0, 15).join(',');
    log('Universe built', data.result);
    await refreshUniverse();
  } catch (e) { log('ERROR universe: ' + e.message); }
};

$('syncMarketBtn').onclick = async () => {
  try {
    const data = await api('/api/sync/market', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value, days: Number($('days').value) }) });
    log('Market synced', data.result);
    await refreshStatus();
  } catch (e) { log('ERROR market: ' + e.message); }
};

$('syncSentimentBtn').onclick = async () => {
  try {
    const data = await api('/api/sync/sentiment', { method: 'POST', body: JSON.stringify({ symbols: symbols(), days: 7, use_llm: false, category: $('category').value, interval: $('interval').value }) });
    log('Sentiment synced', data.result);
    await refreshNews();
  } catch (e) { log('ERROR sentiment: ' + e.message); }
};

$('buildSignalsBtn').onclick = async () => {
  try {
    const data = await api('/api/signals/build', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value }) });
    log('Signals built', data.result);
    await refreshSignals();
    await refreshRank();
  } catch (e) { log('ERROR signals: ' + e.message); }
};

$('rankBtn').onclick = refreshRank;

$('backtestBtn').onclick = async () => {
  try {
    const sym = symbols()[0] || 'BTCUSDT';
    const data = await api('/api/backtest/run', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, strategy: $('strategy').value, limit: 5000 }) });
    log('Backtest', data.result);
    drawEquity(data.result.equity_curve);
    await refreshRank();
  } catch (e) { log('ERROR backtest: ' + e.message); }
};

$('trainBtn').onclick = async () => {
  try {
    const sym = symbols()[0] || 'BTCUSDT';
    const data = await api('/api/ml/train', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, horizon_bars: 12 }) });
    log('ML trained', data.result);
    await refreshRank();
  } catch (e) { log('ERROR train: ' + e.message); }
};

$('predictBtn').onclick = async () => {
  try {
    const sym = symbols()[0] || 'BTCUSDT';
    const data = await api(`/api/ml/predict/latest?symbol=${sym}&category=${$('category').value}&interval=${$('interval').value}&horizon_bars=12`);
    log('ML prediction', data.result);
  } catch (e) { log('ERROR predict: ' + e.message); }
};

refreshStatus();
refreshUniverse();
refreshSignals().catch(() => {});
refreshEquity().catch(() => {});
refreshNews().catch(() => {});
refreshRank().catch(() => {});
