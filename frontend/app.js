const $ = (id) => document.getElementById(id);

const state = {
  status: null,
  universe: [],
  signals: [],
  rank: [],
  news: [],
  sentiment: null,
  equityRun: null,
  selectedId: null,
};

const STRATEGY_LABELS = {
  regime_adaptive_combo: 'Адаптивный режимный фильтр',
  donchian_atr_breakout: 'Donchian + ATR breakout',
  ema_pullback_trend: 'EMA pullback по тренду',
  bollinger_rsi_reversion: 'Bollinger/RSI mean reversion',
  funding_extreme_contrarian: 'Funding contrarian',
  oi_trend_confirmation: 'OI trend confirmation',
  volatility_squeeze_breakout: 'Volatility squeeze breakout',
  sentiment_fear_reversal: 'Fear reversal',
  sentiment_greed_reversal: 'Greed reversal',
};

const REASON_LABELS = {
  price_breaks_20_bar_high_in_uptrend: 'пробой 20-свечного high в восходящем тренде',
  price_breaks_20_bar_low_in_downtrend: 'пробой 20-свечного low в нисходящем тренде',
  pullback_inside_uptrend: 'откат внутри восходящего тренда',
  pullback_inside_downtrend: 'откат внутри нисходящего тренда',
  oversold_near_lower_band: 'перепроданность у нижней полосы Bollinger',
  overbought_near_upper_band: 'перекупленность у верхней полосы Bollinger',
  low_bb_width_with_volume_expansion: 'сжатие волатильности с расширением объема',
  crowded_longs_high_funding: 'перегретые long-позиции и высокий funding',
  crowded_shorts_negative_funding: 'перегретые short-позиции и отрицательный funding',
  price_and_oi_expand_together: 'цена и открытый интерес растут вместе',
  downtrend_with_oi_expansion: 'нисходящий тренд подтвержден ростом OI',
  extreme_fear_plus_technical_exhaustion: 'экстремальный страх и техническое истощение',
  extreme_greed_plus_overbought: 'экстремальная жадность и перекупленность',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function symbols() {
  return $('symbols').value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
}

function num(v, fallback = null) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function fmt(v, d = 4) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return escapeHtml(v);
  if (Math.abs(n) >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + 'B';
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toFixed(d);
}

function pct(v, d = 1) {
  const n = num(v);
  return n === null ? '—' : (n * 100).toFixed(d) + '%';
}

function pctRaw(v, d = 3) {
  const n = num(v);
  return n === null ? '—' : n.toFixed(d) + '%';
}

function dt(v) {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? escapeHtml(v) : d.toLocaleString();
}

function directionPill(direction) {
  const cls = direction === 'long' ? 'long' : direction === 'short' ? 'short' : 'flat';
  return `<span class="pill ${cls}">${escapeHtml(String(direction || 'flat').toUpperCase())}</span>`;
}

function log(title, obj) {
  const payload = obj ? `\n${JSON.stringify(obj, null, 2)}` : '';
  $('log').textContent = `[${new Date().toLocaleTimeString()}] ${title}${payload}\n\n` + $('log').textContent;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || data.raw || res.statusText);
  return data;
}

function rankBySignal(signal) {
  return state.rank.find(r => Number(r.id) === Number(signal.id))
    || state.rank.find(r => r.symbol === signal.symbol && r.strategy === signal.strategy && r.direction === signal.direction)
    || null;
}

function enrichedSignal(signal) {
  const rank = rankBySignal(signal) || {};
  return { ...rank, ...signal, rank };
}

function riskReward(s) {
  const entry = num(s.entry);
  const sl = num(s.stop_loss);
  const tp = num(s.take_profit);
  if (entry === null || sl === null || tp === null || entry <= 0) return null;
  const risk = Math.abs(entry - sl);
  const reward = Math.abs(tp - entry);
  if (risk <= 0) return null;
  return {
    ratio: reward / risk,
    riskPct: risk / entry,
    rewardPct: reward / entry,
  };
}

function maxLossHint(s) {
  const controls = state.status?.risk_controls || {};
  const risk = num(controls.risk_per_trade);
  const notional = num(controls.max_position_notional_usdt);
  const lev = num(controls.max_leverage);
  const pieces = [];
  if (risk !== null) pieces.push(`риск на сделку ${pct(risk, 2)}`);
  if (notional !== null) pieces.push(`notional cap ${fmt(notional, 0)} USDT`);
  if (lev !== null) pieces.push(`плечо ≤ ${fmt(lev, 1)}x`);
  return pieces.length ? pieces.join(' · ') : 'параметры риска не получены';
}

function decisionFor(s) {
  if (!s) return { level: 'no-data', label: 'NO DATA', score: null, title: 'Нет свежих торговых рекомендаций' };
  const rr = riskReward(s);
  const research = num(s.research_score, 0);
  const confidence = num(s.confidence, 0);
  const spread = num(s.spread_pct, 999);
  const dd = num(s.max_drawdown, 0.99);
  const trades = num(s.trades_count, 0);
  const eligible = s.is_eligible === true || String(s.is_eligible).toLowerCase() === 'true';
  const rrRatio = rr?.ratio ?? 0;
  let score = 0;
  score += Math.max(0, Math.min(1, research)) * 32;
  score += Math.max(0, Math.min(1, confidence)) * 22;
  score += Math.max(0, Math.min(1, (rrRatio - 1) / 2)) * 18;
  score += eligible ? 10 : -18;
  score += spread <= 0.08 ? 8 : spread <= 0.15 ? 2 : -8;
  score += trades >= 30 ? 5 : trades >= 10 ? 2 : -4;
  score += dd <= 0.12 ? 5 : dd <= 0.22 ? 1 : -8;
  score = Math.max(0, Math.min(100, Math.round(score)));

  const hardBlock = !eligible || spread > 0.20 || !rr || rrRatio < 1.15 || confidence < 0.50;
  if (hardBlock || score < 45) {
    return { level: 'block', label: 'ЗАПРЕТ', score, title: 'Не передавать оператору для входа' };
  }
  if (score < 68 || confidence < 0.62 || rrRatio < 1.65 || trades < 30) {
    return { level: 'watch', label: 'НАБЛЮДАТЬ', score, title: 'Только ручная проверка, без создания бота' };
  }
  return { level: 'allow', label: 'ПРОВЕРИТЬ', score, title: 'Можно передать оператору на ручную проверку' };
}

function pickDefaultSignal() {
  if (!state.signals.length) return null;
  const candidates = state.signals.map(enrichedSignal);
  candidates.sort((a, b) => {
    const da = decisionFor(a).score ?? -1;
    const db = decisionFor(b).score ?? -1;
    if (db !== da) return db - da;
    return num(b.created_at, 0) - num(a.created_at, 0);
  });
  return candidates[0];
}

function selectedSignal() {
  if (state.selectedId !== null) {
    const signal = state.signals.find(s => Number(s.id) === Number(state.selectedId));
    if (signal) return enrichedSignal(signal);
  }
  return pickDefaultSignal();
}

function evidenceItems(s) {
  const rr = riskReward(s);
  const rationale = typeof s.rationale === 'object' && s.rationale !== null ? s.rationale : {};
  const reason = REASON_LABELS[rationale.reason] || rationale.reason || 'логика стратегии не раскрыта в сигнале';
  const items = [];
  items.push({
    level: num(s.confidence, 0) >= 0.62 ? 'good' : num(s.confidence, 0) >= 0.54 ? 'warn' : 'bad',
    title: `Confidence ${pct(s.confidence, 1)}`,
    text: `Сигнал: ${reason}. Стратегия: ${STRATEGY_LABELS[s.strategy] || s.strategy}.`,
  });
  items.push({
    level: rr && rr.ratio >= 1.65 ? 'good' : rr && rr.ratio >= 1.15 ? 'warn' : 'bad',
    title: `Risk/Reward ${rr ? rr.ratio.toFixed(2) : '—'}`,
    text: rr ? `Риск до SL ${pct(rr.riskPct, 2)}, потенциал до TP ${pct(rr.rewardPct, 2)}.` : 'Невозможно рассчитать риск/прибыль по entry/SL/TP.',
  });
  items.push({
    level: num(s.profit_factor, 0) >= 1.35 && num(s.trades_count, 0) >= 30 ? 'good' : num(s.trades_count, 0) >= 10 ? 'warn' : 'bad',
    title: `История: PF ${fmt(s.profit_factor, 2)} · сделок ${fmt(s.trades_count, 0)}`,
    text: `Sharpe ${fmt(s.sharpe, 2)}, max DD ${pct(s.max_drawdown, 1)}, win rate ${pct(s.win_rate, 1)}. Малое число сделок снижает доверие к рейтингу.`,
  });
  items.push({
    level: num(s.roc_auc, 0.5) >= 0.58 ? 'good' : num(s.roc_auc, 0.5) >= 0.52 ? 'warn' : 'bad',
    title: `ML: ROC AUC ${fmt(s.roc_auc, 3)}`,
    text: `ML probability по сигналу: ${pct(s.ml_probability, 1)}. Если AUC около 0.5, ML не добавляет подтверждения.`,
  });
  items.push({
    level: num(s.sentiment_score, 0) * (s.direction === 'short' ? -1 : 1) >= 0.15 ? 'good' : 'warn',
    title: `Sentiment ${fmt(s.sentiment_score, 3)}`,
    text: 'Sentiment — вспомогательный фильтр; он не должен заменять price action, ликвидность и риск.',
  });
  return items;
}

function guardrailItems(s) {
  const rr = riskReward(s);
  const spread = num(s.spread_pct, 999);
  const eligible = s.is_eligible === true || String(s.is_eligible).toLowerCase() === 'true';
  const staleMs = s.created_at ? Date.now() - new Date(s.created_at).getTime() : Infinity;
  const maxAgeHours = num(state.status?.max_signal_age_hours, 24) || 24;
  return [
    {
      level: eligible ? 'good' : 'bad',
      title: eligible ? 'Ликвидность допустима' : 'Ликвидность не подтверждена',
      text: `Liquidity score ${fmt(s.liquidity_score, 2)}, spread ${pctRaw(spread, 4)}, turnover 24h ${fmt(s.turnover_24h, 1)}.`,
    },
    {
      level: staleMs <= maxAgeHours * 3600_000 ? 'good' : 'bad',
      title: staleMs <= maxAgeHours * 3600_000 ? 'Сигнал свежий' : 'Сигнал устарел',
      text: `Создан: ${dt(s.created_at)}, свеча: ${dt(s.bar_time)}.`,
    },
    {
      level: rr && rr.ratio >= 1.15 ? 'good' : 'bad',
      title: rr && rr.ratio >= 1.15 ? 'SL/TP валидны' : 'SL/TP требуют отклонения',
      text: rr ? `Entry ${fmt(s.entry)}, SL ${fmt(s.stop_loss)}, TP ${fmt(s.take_profit)}.` : 'Нет валидной тройки entry/SL/TP.',
    },
    {
      level: 'warn',
      title: 'Нет автоторговли',
      text: 'Система только рекомендует оператору рассмотреть создание бота. Перед входом нужна ручная сверка стакана, новостей и общего риска портфеля.',
    },
  ];
}

function renderDecision() {
  const s = selectedSignal();
  const decision = decisionFor(s);
  const hero = $('decisionHero');
  const status = $('decisionStatus');
  hero.className = `decision-hero ${decision.level}`;
  status.className = `decision-status ${decision.level}`;
  status.textContent = decision.label;
  $('decisionScore').textContent = decision.score === null ? '—' : String(decision.score);
  if (!s) {
    $('decisionTitle').textContent = decision.title;
    $('decisionSubtitle').textContent = 'Сначала синхронизируйте рынок и постройте рекомендации. Экран не отправляет ордера и не создает ботов автоматически.';
    $('tradePlan').className = 'trade-plan empty-state';
    $('tradePlan').textContent = 'Выберите кандидата из списка ниже.';
    $('evidenceList').className = 'evidence-list empty-state';
    $('evidenceList').textContent = 'Нет выбранного сигнала.';
    $('guardrails').className = 'guardrails empty-state';
    $('guardrails').textContent = 'Нет данных для проверки ограничений.';
    return;
  }
  state.selectedId = Number(s.id);
  const rr = riskReward(s);
  $('decisionTitle').textContent = `${decision.title}: ${s.symbol} ${String(s.direction).toUpperCase()}`;
  $('decisionSubtitle').textContent = `${STRATEGY_LABELS[s.strategy] || s.strategy}. Итоговая оценка учитывает confidence, backtest, ML, ликвидность, spread, риск/прибыль и свежесть сигнала.`;

  $('tradePlan').className = 'trade-plan';
  $('tradePlan').innerHTML = `
    <div class="trade-title">
      <div><h3>${escapeHtml(s.symbol)} ${directionPill(s.direction)}</h3><small>${escapeHtml(STRATEGY_LABELS[s.strategy] || s.strategy)}</small></div>
      <span class="card-status ${decision.level}">${decision.label}</span>
    </div>
    <div class="metric-grid">
      <div class="metric"><span>Entry</span><strong>${fmt(s.entry)}</strong></div>
      <div class="metric bad"><span>Stop Loss</span><strong>${fmt(s.stop_loss)}</strong></div>
      <div class="metric good"><span>Take Profit</span><strong>${fmt(s.take_profit)}</strong></div>
      <div class="metric ${rr && rr.ratio >= 1.65 ? 'good' : 'warn'}"><span>Risk/Reward</span><strong>${rr ? rr.ratio.toFixed(2) : '—'}</strong></div>
      <div class="metric"><span>Confidence</span><strong>${pct(s.confidence, 1)}</strong></div>
      <div class="metric"><span>Research score</span><strong>${fmt(s.research_score, 3)}</strong></div>
    </div>
    <p><b>Ограничение позиции:</b> ${escapeHtml(maxLossHint(s))}.</p>
    <p><b>Инвалидация:</b> не входить, если цена ушла за SL до ручного подтверждения, spread расширился, ликвидность стала недопустимой или появился конфликтующий новостной риск.</p>
  `;

  $('evidenceList').className = 'evidence-list';
  $('evidenceList').innerHTML = evidenceItems(s).map(item => `
    <div class="evidence-item">
      <i class="icon-dot ${item.level}"></i>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></div>
    </div>`).join('');

  $('guardrails').className = 'guardrails';
  $('guardrails').innerHTML = guardrailItems(s).map(item => `
    <div class="guard-item">
      <i class="icon-dot ${item.level}"></i>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></div>
    </div>`).join('');

  document.querySelectorAll('.candidate-card').forEach(card => {
    card.classList.toggle('active', Number(card.dataset.id) === Number(s.id));
  });
}

function renderCandidates() {
  const box = $('candidateList');
  if (!state.signals.length) {
    box.className = 'candidate-list empty-state';
    box.textContent = 'Кандидаты появятся после построения сигналов.';
    renderDecision();
    return;
  }
  const candidates = state.signals.map(enrichedSignal).sort((a, b) => (decisionFor(b).score ?? -1) - (decisionFor(a).score ?? -1));
  box.className = 'candidate-list';
  box.innerHTML = candidates.map(s => {
    const d = decisionFor(s);
    const rr = riskReward(s);
    return `
      <article class="candidate-card ${d.level}" data-id="${escapeHtml(s.id)}">
        <div class="candidate-top">
          <div>
            <div class="candidate-symbol">${escapeHtml(s.symbol)} ${directionPill(s.direction)}</div>
            <div class="candidate-strategy">${escapeHtml(STRATEGY_LABELS[s.strategy] || s.strategy)}</div>
          </div>
          <span class="card-status ${d.level}">${d.label}</span>
        </div>
        <div class="candidate-metrics">
          <div><span>Score</span><strong>${d.score}</strong></div>
          <div><span>Conf</span><strong>${pct(s.confidence, 0)}</strong></div>
          <div><span>R/R</span><strong>${rr ? rr.ratio.toFixed(2) : '—'}</strong></div>
          <div><span>Spread</span><strong>${pctRaw(s.spread_pct, 3)}</strong></div>
        </div>
      </article>`;
  }).join('');
  box.querySelectorAll('.candidate-card').forEach(card => {
    card.onclick = () => {
      state.selectedId = Number(card.dataset.id);
      renderDecision();
      $('briefBox').textContent = 'Нажмите LLM brief для выбранного кандидата.';
    };
  });
  renderDecision();
}

function renderTables() {
  const rankBody = $('rankTable').querySelector('tbody');
  rankBody.innerHTML = state.rank.map(r => `
    <tr>
      <td>${fmt(r.research_score, 3)}</td><td>${escapeHtml(r.symbol)}</td><td>${escapeHtml(r.strategy)}</td><td>${directionPill(r.direction)}</td>
      <td>${fmt(r.confidence, 3)}</td><td>${fmt(r.profit_factor, 2)}</td><td>${fmt(r.sharpe, 2)}</td><td>${fmt(r.max_drawdown, 3)}</td><td>${fmt(r.roc_auc, 3)}</td><td>${fmt(r.spread_pct, 4)}</td>
    </tr>`).join('');

  const signalsBody = $('signalsTable').querySelector('tbody');
  signalsBody.innerHTML = state.signals.map(s => `
    <tr>
      <td>${escapeHtml(s.id)}</td><td>${dt(s.created_at)}</td><td>${escapeHtml(s.symbol)}</td><td>${escapeHtml(s.strategy)}</td>
      <td>${directionPill(s.direction)}</td><td>${fmt(s.confidence, 3)}</td><td>${fmt(s.entry, 4)}</td><td>${fmt(s.stop_loss, 4)}</td><td>${fmt(s.take_profit, 4)}</td>
    </tr>`).join('');

  const universeBody = $('universeTable').querySelector('tbody');
  universeBody.innerHTML = state.universe.map(r => {
    const comp = r.components || {};
    return `<tr><td>${escapeHtml(r.rank_no)}</td><td>${escapeHtml(r.symbol)}</td><td>${escapeHtml(r.reason || '—')}</td><td>${fmt(r.liquidity_score, 3)}</td><td>${fmt(comp.spread_pct, 4)}</td><td>${fmt(comp.turnover_24h, 1)}</td><td>${fmt(comp.open_interest_value, 1)}</td></tr>`;
  }).join('');
}

async function refreshStatus() {
  const data = await api('/api/status');
  state.status = data;
  $('statusBox').textContent = 'OK · DB ' + (data.db_time || '—');
  $('statusBox').className = 'status ok';
  $('kpiCandles').textContent = data.candles ?? '—';
  $('kpiSentiment').textContent = data.sentiment_sources?.cryptopanic ? 'Free+CP' : 'Free';
}

async function refreshUniverse() {
  const mode = $('universeMode').value;
  const data = await api(`/api/symbols/universe/latest?category=${encodeURIComponent($('category').value)}&mode=${encodeURIComponent(mode)}&limit=50`);
  state.universe = data.items || [];
  $('kpiUniverse').textContent = state.universe.length || '—';
  renderTables();
}

async function refreshSignals() {
  const data = await api('/api/signals/latest?limit=40');
  state.signals = data.signals || [];
  if (state.selectedId !== null && !state.signals.some(s => Number(s.id) === Number(state.selectedId))) state.selectedId = null;
  renderTables();
  renderCandidates();
}

async function refreshRank() {
  const data = await api(`/api/research/rank?category=${encodeURIComponent($('category').value)}&interval=${encodeURIComponent($('interval').value)}&limit=30`);
  state.rank = data.items || [];
  renderTables();
  renderCandidates();
}

function drawEquity(curve) {
  const canvas = $('equityCanvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#080d14';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!curve || curve.length < 2) return;
  const vals = curve.map(p => Number(p.equity)).filter(Number.isFinite);
  if (vals.length < 2) return;
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = 28;
  ctx.strokeStyle = '#253244';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = pad + i * (canvas.height - pad * 2) / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(canvas.width - pad, y); ctx.stroke();
  }
  ctx.strokeStyle = '#78d4ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = pad + i * (canvas.width - pad * 2) / (vals.length - 1);
    const y = canvas.height - pad - ((v - min) / Math.max(max - min, 1e-9)) * (canvas.height - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#d8eaff';
  ctx.font = '12px system-ui';
  ctx.fillText(`min ${fmt(min, 2)} · max ${fmt(max, 2)}`, pad, 18);
}

async function refreshEquity() {
  const data = await api('/api/equity/latest?limit=1');
  state.equityRun = data.runs?.[0] || null;
  if (state.equityRun) {
    $('equityMeta').textContent = `${state.equityRun.symbol} · ${state.equityRun.strategy} · return ${pct(state.equityRun.total_return, 1)} · DD ${pct(state.equityRun.max_drawdown, 1)}`;
    drawEquity(state.equityRun.equity_curve);
  }
}

async function refreshNews() {
  const sym = symbols()[0] || 'BTCUSDT';
  const data = await api(`/api/news/latest?symbol=${encodeURIComponent(sym)}&limit=8`);
  state.news = data.news || [];
  $('newsList').innerHTML = state.news.length ? state.news.map(n => `
    <div class="news-item">
      <b>${escapeHtml(n.symbol)}</b> <span>${escapeHtml(n.source || '')}</span>
      <p>${escapeHtml(n.title || '')}</p>
      <small>${n.published_at ? dt(n.published_at) : ''} · score ${fmt(n.llm_score ?? n.sentiment_score, 3)}</small>
      ${n.url ? `<div><a href="${escapeHtml(n.url)}" target="_blank" rel="noreferrer">Источник</a></div>` : ''}
    </div>`).join('') : '<div class="empty-state">Новостей пока нет.</div>';
  const s = await api(`/api/sentiment/summary?symbol=${encodeURIComponent(sym)}&limit=6`);
  state.sentiment = s.result;
  const score = s.result?.score ?? s.result?.summary_score ?? null;
  $('sentimentSummary').textContent = score === null || score === undefined ? `Сводка: ${sym}` : `Сводка ${sym}: ${fmt(score, 3)}`;
}

async function refreshAll() {
  try {
    await refreshStatus();
    await Promise.allSettled([refreshUniverse(), refreshRank(), refreshSignals(), refreshEquity(), refreshNews()]);
  } catch (e) {
    $('statusBox').textContent = 'DB/API error';
    $('statusBox').className = 'status error';
    log('ERROR refresh: ' + e.message);
  }
}

async function runOperation(title, fn) {
  try {
    const result = await fn();
    log(title, result);
    return result;
  } catch (e) {
    log('ERROR ' + title + ': ' + e.message);
    throw e;
  }
}

$('refreshAllBtn').onclick = refreshAll;

$('syncUniverseBtn').onclick = async () => {
  await runOperation('Universe built', async () => {
    const data = await api('/api/symbols/universe/build', { method: 'POST', body: JSON.stringify({ category: $('category').value, mode: $('universeMode').value, limit: 25, refresh: true }) });
    $('symbols').value = (data.result.symbols || []).slice(0, 15).join(',');
    await refreshUniverse();
    return data.result;
  });
};

$('syncMarketBtn').onclick = async () => {
  await runOperation('Market synced', async () => {
    const data = await api('/api/sync/market', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value, days: Number($('days').value) }) });
    await refreshStatus();
    return data.result;
  });
};

$('syncSentimentBtn').onclick = async () => {
  await runOperation('Sentiment synced', async () => {
    const data = await api('/api/sync/sentiment', { method: 'POST', body: JSON.stringify({ symbols: symbols(), days: 7, use_llm: false, category: $('category').value, interval: $('interval').value }) });
    await refreshNews();
    return data.result;
  });
};

$('buildSignalsBtn').onclick = async () => {
  await runOperation('Signals built', async () => {
    const data = await api('/api/signals/build', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value }) });
    await refreshRank();
    await refreshSignals();
    return data.result;
  });
};

$('rankBtn').onclick = async () => runOperation('Rank refreshed', refreshRank);

$('backtestBtn').onclick = async () => {
  await runOperation('Backtest', async () => {
    const s = selectedSignal();
    const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
    const strategy = s?.strategy || $('strategy').value;
    const data = await api('/api/backtest/run', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, strategy, limit: 5000 }) });
    drawEquity(data.result.equity_curve);
    await refreshRank();
    return data.result;
  });
};

$('trainBtn').onclick = async () => {
  await runOperation('ML trained', async () => {
    const s = selectedSignal();
    const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
    const data = await api('/api/ml/train', { method: 'POST', body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, horizon_bars: 12 }) });
    await refreshRank();
    return data.result;
  });
};

$('predictBtn').onclick = async () => {
  await runOperation('ML prediction', async () => {
    const s = selectedSignal();
    const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
    const data = await api(`/api/ml/predict/latest?symbol=${encodeURIComponent(sym)}&category=${encodeURIComponent($('category').value)}&interval=${encodeURIComponent($('interval').value)}&horizon_bars=12`);
    return data.result;
  });
};

$('briefBtn').onclick = async () => {
  const s = selectedSignal();
  if (!s) {
    $('briefBox').textContent = 'Нет выбранного сигнала.';
    return;
  }
  try {
    $('briefBox').textContent = 'LLM формирует brief...';
    const b = await api('/api/llm/brief', { method: 'POST', body: JSON.stringify({ signal_id: Number(s.id) }) });
    $('briefBox').textContent = b.brief;
  } catch (e) {
    $('briefBox').textContent = e.message;
  }
};

refreshAll();
