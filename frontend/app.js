const $ = (id) => document.getElementById(id);
document.body.classList.add('compact-ui');

const state = {
  status: null,
  rank: [],
  signals: [],
  universe: [],
  news: [],
  selectedId: null,
  filter: 'all',
  equityRun: null,
  llmStatus: null,
  llmSummary: null,
  llmEvaluations: [],
  backtestStatus: null,
  backtestSummary: null,
  signalStatus: null,
  contextTab: 'risk',
  entryInterval: '15',
  recommendationIntervals: ['15'],
  contextIntervals: ['60', '240'],
};

const STRATEGY_LABELS = {
  regime_adaptive_combo: 'адаптивный режим',
  donchian_atr_breakout: 'пробой Donchian/ATR',
  ema_pullback_trend: 'откат к EMA по тренду',
  bollinger_rsi_reversion: 'возврат к среднему Bollinger/RSI',
  funding_extreme_contrarian: 'контртренд по funding',
  oi_trend_confirmation: 'подтверждение через OI',
  volatility_squeeze_breakout: 'выход из сжатия волатильности',
  sentiment_fear_reversal: 'разворот от страха',
  sentiment_greed_reversal: 'разворот от жадности',
};

const REASON_LABELS = {
  price_breaks_20_bar_high_in_uptrend: 'пробой 20-свечного high в восходящем тренде',
  price_breaks_20_bar_low_in_downtrend: 'пробой 20-свечного low в нисходящем тренде',
  pullback_inside_uptrend: 'откат внутри восходящего тренда',
  pullback_inside_downtrend: 'откат внутри нисходящего тренда',
  oversold_near_lower_band: 'перепроданность около нижней полосы Bollinger',
  overbought_near_upper_band: 'перекупленность около верхней полосы Bollinger',
  low_bb_width_with_volume_expansion: 'сжатие волатильности с расширением объема',
  crowded_longs_high_funding: 'перегретые long-позиции и высокий funding',
  crowded_shorts_negative_funding: 'перегретые short-позиции и отрицательный funding',
  price_and_oi_expand_together: 'цена и открытый интерес растут вместе',
  downtrend_with_oi_expansion: 'нисходящий тренд подтверждён ростом OI',
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


function cleanLlmText(value) {
  return String(value ?? '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^[\s>*#\-–—]+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function cssToken(value, fallback = 'neutral') {
  const token = String(value ?? '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
  return token || fallback;
}

function safeExternalUrl(value) {
  if (!value) return '';
  try {
    const url = new URL(String(value), window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}

function setBusy(isBusy) {
  document.body.classList.toggle('is-busy', isBusy);
  document.body.setAttribute('aria-busy', isBusy ? 'true' : 'false');
  // Блокируем только кнопки, которые запускают API-операции. Навигация, вкладки,
  // фильтры и сворачивание панелей должны оставаться рабочими даже во время долгого запроса.
  document.querySelectorAll('button[data-busy-lock="true"]').forEach((button) => {
    button.disabled = isBusy;
  });
}

function selectedSymbols() {
  return $('symbols').value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
}

function intervals() {
  return $('interval').value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
}

function primaryInterval() {
  return state.entryInterval || intervals()[0] || '15';
}

function num(value, fallback = null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return escapeHtml(value);
  if (Math.abs(n) >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(digits);
}

function pct(value, digits = 1) {
  const n = num(value);
  return n === null ? '—' : `${(n * 100).toFixed(digits)}%`;
}

function pctRaw(value, digits = 3) {
  const n = num(value);
  return n === null ? '—' : `${n.toFixed(digits)}%`;
}

function dt(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? escapeHtml(value) : d.toLocaleString();
}

function compactDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function ageMinutes(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 60_000));
}

function ageText(value) {
  if (!value) return 'нет времени';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'время не распознано';
  const minutes = Math.max(0, Math.round((Date.now() - d.getTime()) / 60_000));
  if (minutes < 60) return `${minutes} мин назад`;
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)} ч назад`;
  return `${(minutes / 1440).toFixed(1)} дн назад`;
}

function llmLifeText(updatedAt) {
  const minutes = ageMinutes(updatedAt);
  const ttl = num(state.llmStatus?.ttl_minutes, 60) || 60;
  if (minutes === null) return `Возраст: — · TTL ${ttl} мин`;
  const left = Math.max(0, ttl - minutes);
  return `Возраст ${minutes} мин · TTL ${ttl} мин · осталось ${left} мин`;
}

const DEFAULT_API_TIMEOUT_MS = 45_000;
const SENTIMENT_OPERATION_TIMEOUT_MS = 180_000;
const LONG_OPERATION_TIMEOUT_MS = 360_000;

function marketSyncTimeoutMs() {
  const symbolCount = Math.max(1, selectedSymbols().length);
  const intervalCount = Math.max(1, intervals().length);
  const requestedDays = Math.max(1, num($('days')?.value, 30) || 30);
  // Market sync делает несколько внешних Bybit-запросов на каждый symbol/interval.
  // 45 секунд достаточно для коротких API-вызовов, но слишком мало для первичной загрузки истории.
  const estimated = 90_000 + symbolCount * intervalCount * Math.min(requestedDays, 365) * 700;
  return Math.min(900_000, Math.max(LONG_OPERATION_TIMEOUT_MS, estimated));
}

async function api(path, options = {}, timeoutMs = DEFAULT_API_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  try {
    const res = await fetch(path, {
      ...options,
      headers,
      signal: options.signal || controller.signal,
    });
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!res.ok) throw new Error(data.detail || data.raw || res.statusText);
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`API timeout after ${Math.round(timeoutMs / 1000)}s: ${path}`);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function safeStringify(value) {
  const seen = new WeakSet();
  return JSON.stringify(value, (key, val) => {
    if (typeof val === 'object' && val !== null) {
      if (seen.has(val)) return '[Circular]';
      seen.add(val);
    }
    return val;
  }, 2);
}

function log(title, obj) {
  const logBox = $('log');
  if (!logBox) return;
  let payload = '';
  if (obj) {
    try {
      payload = `\n${safeStringify(obj)}`;
    } catch {
      payload = `\n${String(obj)}`;
    }
  }
  logBox.textContent = `[${new Date().toLocaleTimeString()}] ${title}${payload}\n\n${logBox.textContent}`;
  logBox.scrollTop = 0;
}

function setEquitySource(text, tone = 'neutral') {
  const box = $('equitySourceBox');
  if (!box) return;
  box.textContent = text;
  box.className = `chart-explainer ${cssToken(tone, 'neutral')}`;
}

function compactStrategy(value) {
  return STRATEGY_LABELS[value] || value || 'стратегия не указана';
}

function equityRunMatchesSelected(run, s) {
  if (!run || !s) return false;
  const runSymbol = String(run.symbol || '').toUpperCase();
  const selectedSymbol = String(s.symbol || '').toUpperCase();
  const runStrategy = String(run.strategy || '');
  const selectedStrategy = String(s.strategy || '');
  return runSymbol && selectedSymbol && runSymbol === selectedSymbol && (!runStrategy || !selectedStrategy || runStrategy === selectedStrategy);
}

function syncEquitySelectionNote(s) {
  if (!state.equityRun) {
    setEquitySource('Equity-кривая пока не загружена. Выбор кандидата слева не строит график; нажмите «Бэктест сетапа», чтобы построить кривую именно для выбранного рынка.', 'neutral');
    return;
  }
  const runSymbol = String(state.equityRun.symbol || '—').toUpperCase();
  const runStrategy = compactStrategy(state.equityRun.strategy);
  if (equityRunMatchesSelected(state.equityRun, s)) {
    setEquitySource(`График соответствует выбранному рынку ${runSymbol}. Источник: последняя сохранённая equity-кривая /api/equity/latest; перерисовка — «Бэктест сетапа» или «Обновить все».`, 'ok');
    return;
  }
  const selected = s?.symbol ? `${String(s.symbol).toUpperCase()} · ${compactStrategy(s.strategy)}` : 'кандидат не выбран';
  setEquitySource(`График НЕ меняется от простого выбора строки. Сейчас показан последний сохранённый бэктест: ${runSymbol} · ${runStrategy}. Выбрано: ${selected}. Для выбранного рынка нажмите «Бэктест сетапа».`, 'warn');
}

function hasNumber(value) {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
}

function mlEvidenceStatus(s) {
  if (!hasNumber(s?.roc_auc)) return 'warn';
  const rocAuc = num(s?.roc_auc, 0.5);
  if (rocAuc >= 0.58) return 'pass';
  if (rocAuc >= 0.48) return 'warn';
  return 'fail';
}

function mlEvidenceTitle(s) {
  if (!hasNumber(s?.roc_auc)) return 'ML ещё не обучен · жёлтый';
  const rocAuc = num(s?.roc_auc, 0.5);
  const zone = rocAuc >= 0.58 ? 'зелёный ≥0.58' : rocAuc >= 0.48 ? 'жёлтый 0.48–0.58' : 'красный <0.48';
  return `ML ROC-AUC ${fmt(rocAuc, 3)} · ${zone}`;
}

function mlEvidenceText(s) {
  const research = num(s?.research_score, 0);
  if (!hasNumber(s?.roc_auc)) {
    return `ML-модель для этого symbol/TF пока не найдена. Это снижает доказательность, но не является hard-veto для ручного research queue. Research score ${fmt(research, 3)}.`;
  }
  const rocAuc = num(s?.roc_auc, 0.5);
  const direction = rocAuc < 0.5 ? 'Значение ниже 0.50 хуже случайного ориентира.' : 'Значение около 0.50 не даёт доказательного ML-подтверждения.';
  return `Зелёный статус появляется только при ROC-AUC ≥0.58; жёлтый — 0.48–0.58; красный — ниже 0.48. ${direction} Research score ${fmt(research, 3)}.`;
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function setMeter(cardSelector, barId, value, tone = 'neutral', label = null) {
  const bar = $(barId);
  const card = bar?.closest(cardSelector);
  const pctValue = Math.max(0, Math.min(100, num(value, 0) || 0));
  if (bar) bar.style.width = `${pctValue}%`;
  if (card) {
    card.classList.remove('good', 'warn', 'bad', 'neutral');
    card.classList.add(tone);
  }
  return label ?? `${Math.round(pctValue)}%`;
}

function priceFmt(value) {
  const n = num(value);
  if (n === null) return '—';
  if (Math.abs(n) >= 1000) return n.toLocaleString([], { maximumFractionDigits: 2 });
  if (Math.abs(n) >= 1) return n.toLocaleString([], { maximumFractionDigits: 4 });
  return n.toLocaleString([], { maximumSignificantDigits: 6 });
}

function updateTopContext(s) {
  setText('activePairChip', `Pair ${s?.symbol || selectedSymbols()[0] || '—'}`);
  setText('activeTimeframeChip', `TF ${s?.interval || primaryInterval() || '—'}`);
  setText('lastUpdateChip', `Update ${compactDateTime(s?.created_at || state.status?.db_time || new Date())}`);
}

function renderDecisionMeters(s, d) {
  const rr = riskReward(s);
  const confidence = num(s?.confidence, null);
  const riskValue = s ? Math.round(Math.min(100, Math.max(0,
    (num(s.spread_pct, 0) > 0.15 ? 25 : num(s.spread_pct, 0) > 0.08 ? 12 : 4)
    + Math.min(35, Math.max(0, num(s.max_drawdown, 0) * 100))
    + (mtfSeverity(s) === 'fail' ? 30 : mtfSeverity(s) === 'warn' ? 14 : 0)
    + (decisionFor(s).level === 'reject' ? 18 : decisionFor(s).level === 'watch' ? 8 : 0)
  ))) : 0;
  const rrValue = rr ? Math.min(100, Math.round((rr.ratio / 3) * 100)) : 0;
  setText('confidenceMeterValue', confidence === null ? '—' : pct(confidence, 0));
  setText('riskMeterValue', s ? `${riskValue}/100` : '—');
  setText('rrMeterValue', rr ? rr.ratio.toFixed(2) : '—');
  setMeter('.confidence-meter', 'confidenceMeterBar', confidence === null ? 0 : confidence * 100, confidence >= 0.62 ? 'good' : confidence >= 0.54 ? 'warn' : 'bad');
  setMeter('.risk-meter', 'riskMeterBar', riskValue, riskValue <= 35 ? 'good' : riskValue <= 62 ? 'warn' : 'bad');
  setMeter('.risk-reward-card', 'rrMeterBar', rrValue, rr && rr.ratio >= 1.55 ? 'good' : rr && rr.ratio >= 1.15 ? 'warn' : 'bad');
}

function renderExecutionMap(s) {
  const box = $('executionMap');
  if (!box) return;
  if (!s) {
    box.className = 'execution-map empty-state';
    box.textContent = 'Выберите кандидата: здесь появятся entry, stop-loss, take-profit и визуальный сценарий сделки.';
    return;
  }
  const rr = riskReward(s);
  const direction = String(s.direction || 'flat').toUpperCase();
  box.className = `execution-map ${cssToken(s.direction, 'neutral')}`;
  box.innerHTML = `
    <div class="execution-level entry"><span>Entry · ${escapeHtml(direction)}</span><strong>${priceFmt(s.entry)}</strong></div>
    <div class="execution-level stop"><span>Stop-loss</span><strong>${priceFmt(s.stop_loss)}</strong></div>
    <div class="execution-level take"><span>Take-profit</span><strong>${priceFmt(s.take_profit)}</strong></div>
    <div class="execution-level rr"><span>Risk / Reward</span><strong>${rr ? rr.ratio.toFixed(2) : '—'}</strong></div>`;
}

function showOperationStatus(message, tone = 'neutral') {
  const safeTone = ['neutral', 'busy', 'ok', 'warn', 'error'].includes(tone) ? tone : 'neutral';
  ['operationToast', 'operationStatus'].forEach((id) => {
    const node = $(id);
    if (!node) return;
    node.className = `${id === 'operationToast' ? 'operation-toast' : 'operation-status'} ${safeTone}`;
    node.textContent = message;
  });
}

function validateInputs({ requireSymbols = false } = {}) {
  const days = Number($('days')?.value);
  if (!Number.isFinite(days) || days < 1 || days > 730) {
    throw new Error('Дней истории должно быть числом от 1 до 730.');
  }
  if (!$('category')?.value.trim()) throw new Error('Категория не задана.');
  if (!intervals().length) throw new Error('MTF контур не задан.');
  if (requireSymbols && !selectedSymbols().length) throw new Error('Укажите хотя бы один символ.');
}

function openTechnicalDetails() {
  const details = $('technicalDetails');
  if (details) details.open = true;
}

function scrollToElement(id) {
  const node = $(id);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function activateNav(button) {
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item === button);
    if (item === button) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
}

function rankBySignal(signal) {
  return state.rank.find((r) => Number(r.id) === Number(signal.id))
    || state.rank.find((r) => r.symbol === signal.symbol && r.interval === signal.interval && r.strategy === signal.strategy && r.direction === signal.direction)
    || {};
}

function enrichedSignal(signal) {
  const rank = rankBySignal(signal);
  return withLlmFields({ ...rank, ...signal, rank });
}

function riskReward(s) {
  const entry = num(s?.entry);
  const stop = num(s?.stop_loss);
  const target = num(s?.take_profit);
  if (entry === null || stop === null || target === null || entry <= 0) return null;
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  if (risk <= 0 || reward <= 0) return null;
  return {
    ratio: reward / risk,
    riskPct: risk / entry,
    rewardPct: reward / entry,
  };
}

function bool(value) {
  return value === true || String(value).toLowerCase() === 'true';
}

function evaluationBySignal(item) {
  if (!item?.id) return null;
  return state.llmEvaluations.find((e) => Number(e.signal_id) === Number(item.id)) || null;
}

function withLlmFields(item) {
  const evalRow = evaluationBySignal(item);
  if (!evalRow) return item;
  return {
    ...item,
    llm_status: item.llm_status || evalRow.status,
    llm_brief: item.llm_brief || evalRow.brief,
    llm_error: item.llm_error || evalRow.error,
    llm_model: item.llm_model || evalRow.model,
    llm_updated_at: item.llm_updated_at || evalRow.updated_at,
    llm_duration_ms: item.llm_duration_ms || evalRow.duration_ms,
    llm_payload_hash: item.llm_payload_hash || evalRow.payload_hash,
  };
}

function setOpsPanelOpen(open) {
  const panel = $('opsPanel');
  const body = $('opsBody');
  const toggle = $('opsToggleBtn');
  const stateLabel = $('opsToggleState');
  if (!panel || !body || !toggle) return;

  panel.classList.toggle('open', open);
  body.hidden = !open;
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (stateLabel) stateLabel.textContent = open ? 'Свернуть панель ↑' : 'Открыть панель ↓';
  setText('opsHelper', open ? 'Параметры развернуты. Нажмите, чтобы свернуть.' : 'Символы, MTF, стратегия и ручные операции.');
}

function toggleOpsPanel() {
  const panel = $('opsPanel');
  setOpsPanelOpen(!panel?.classList.contains('open'));
}


const MTF_STATUS_LABELS = {
  aligned_intraday: '15m+60m+240m согласованы',
  aligned_bias: '15m подтвержден 60m',
  tactical_only: 'Только 15m',
  weak_alignment: 'Слабая MTF-связь',
  no_trade_conflict: 'Конфликт старших TF',
  context_only: 'Контекст, не вход',
  invalid_direction: 'Нет направления',
};

const MTF_ACTION_LABELS = {
  HIGH_CONVICTION_INTRADAY: 'HIGH CONVICTION',
  BIAS_ALIGNED_INTRADAY: 'BIAS ALIGNED',
  TACTICAL_ONLY: 'TACTICAL',
  LOW_CONVICTION_INTRADAY: 'LOW CONVICTION',
  NO_TRADE_CONFLICT: 'NO TRADE',
  CONTEXT_ONLY: 'CONTEXT',
  NO_TRADE_INVALID: 'NO TRADE',
};

function mtfLabel(s) {
  if (!s) return 'MTF: нет данных';
  return MTF_STATUS_LABELS[s.mtf_status] || s.mtf_status || 'MTF: не рассчитан';
}

function mtfSeverity(s) {
  if (!s) return 'fail';
  if (!s.mtf_status) return 'warn';
  if (s.mtf_veto || s.higher_tf_conflict || s.mtf_status === 'no_trade_conflict' || s.mtf_status === 'context_only') return 'fail';
  if (s.mtf_status === 'tactical_only' || s.mtf_status === 'weak_alignment') return 'warn';
  return 'pass';
}

function tfCell(title, tf) {
  const direction = String(tf?.direction || 'neutral').toLowerCase();
  const cls = direction === 'long' ? 'long' : direction === 'short' ? 'short' : 'neutral';
  return `
    <div class="tf-cell ${cls}">
      <span>${escapeHtml(title)} · ${escapeHtml(tf?.interval || '—')}</span>
      <b>${escapeHtml(direction.toUpperCase())}</b>
      <small>L ${fmt(tf?.long_strength, 2)} · S ${fmt(tf?.short_strength, 2)} · n=${escapeHtml(tf?.signals ?? 0)}</small>
    </div>`;
}

function renderMtfMatrix(s) {
  const box = $('mtfMatrix');
  if (!box) return;
  if (!s) {
    box.className = 'mtf-matrix empty-state';
    box.textContent = 'Нет выбранного кандидата.';
    return;
  }
  const sev = mtfSeverity(s);
  box.className = `mtf-matrix ${sev}`;
  box.innerHTML = `
    <div class="mtf-state-row">
      <span class="mtf-pill ${sev}">${escapeHtml(MTF_ACTION_LABELS[s.mtf_action_class] || s.mtf_action_class || 'MTF')}</span>
      <strong>${escapeHtml(mtfLabel(s))}</strong>
      <small>${escapeHtml(s.mtf_reason || 'MTF-контекст не раскрыт.')}</small>
    </div>
    <div class="tf-grid">
      ${tfCell('ENTRY', s.mtf_entry)}
      ${tfCell('BIAS', s.mtf_bias)}
      ${tfCell('REGIME', s.mtf_regime)}
    </div>`;
}


function setContextTab(tabName) {
  state.contextTab = tabName || 'risk';
  document.querySelectorAll('.context-tab').forEach((button) => {
    const active = button.dataset.tab === state.contextTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.context-tab-panel').forEach((panel) => {
    const active = panel.dataset.panel === state.contextTab;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function llmStateText(s) {
  if (!s) return 'LLM: нет сетапа';
  const verdict = llmVerdictFor(s);
  if (verdict.state === 'running') return 'LLM: анализируется';
  if (verdict.state === 'error') return 'LLM: ошибка';
  if (verdict.state === 'ok') return `LLM: ${verdict.recommendation} · ${verdict.confidenceText} · ${verdict.timeText}`;
  return 'LLM: ожидает фонового цикла';
}

function truncateText(value, limit = 180) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 1)).trim()}…` : text;
}

function parseMaybeJsonObject(text) {
  const raw = String(text || '').trim();
  const start = raw.indexOf('{');
  const end = raw.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    const parsed = JSON.parse(raw.slice(start, end + 1));
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function normalizeLlmRecommendation(value) {
  const text = String(value || '').toLowerCase();
  if (/\b(long|buy)\b|лонг|покуп/.test(text)) return 'LONG';
  if (/\b(short|sell)\b|шорт|продаж/.test(text)) return 'SHORT';
  if (/\b(neutral|flat|wait|hold|no[_\s-]?trade|avoid)\b|нейтрал|наблюд|ожид|нет\s+вход|вход\s+не\s+подтверж|не\s+подтверж|запрещ/.test(text)) return 'NEUTRAL';
  return null;
}

function extractStructuredLine(text, keys) {
  const pattern = new RegExp(`(?:^|\\n)\\s*(?:${keys.join('|')})\\s*[:：=—-]\\s*([^\\n]+)`, 'i');
  const match = String(text || '').match(pattern);
  return match?.[1]?.trim() || '';
}

function extractLlmConfidence(text, parsed = null) {
  const direct = parsed?.confidence ?? parsed?.llm_confidence ?? parsed?.confidence_score ?? parsed?.score;
  if (direct !== undefined && direct !== null && direct !== '') {
    const n = Number(String(direct).replace(',', '.').replace('%', ''));
    if (Number.isFinite(n)) return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
  }
  const line = extractStructuredLine(text, ['LLM_CONFIDENCE', 'CONFIDENCE', 'CONFIDENCE_SCORE', 'УВЕРЕННОСТЬ', 'УВЕРЕННОСТЬ LLM']);
  const match = line.match(/(\d{1,3}(?:[\.,]\d+)?)/) || String(text || '').match(/(?:confidence|уверенность)[^0-9]{0,24}(\d{1,3}(?:[\.,]\d+)?)/i);
  if (!match) return null;
  const n = Number(match[1].replace(',', '.'));
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, n <= 1 ? n * 100 : n));
}

function extractLlmRationale(text, parsed = null) {
  const direct = parsed?.rationale ?? parsed?.reason ?? parsed?.comment ?? parsed?.explanation;
  if (direct) return truncateText(cleanLlmText(direct), 260);
  const explicit = extractStructuredLine(text, ['RATIONALE', 'REASON', 'EXPLANATION', 'ОБОСНОВАНИЕ', 'ПРИЧИНА']);
  if (explicit) return truncateText(cleanLlmText(explicit), 260);
  const lines = String(text || '')
    .split('\n')
    .map((line) => cleanLlmText(line))
    .filter(Boolean)
    .filter((line) => !/^(LLM_)?(RECOMMENDATION|VERDICT|DIRECTION|CONFIDENCE|TIME)|^(ВЕРДИКТ|НАПРАВЛЕНИЕ|УВЕРЕННОСТЬ)/i.test(line));
  return truncateText(lines.join(' · '), 260);
}

function parseLlmBrief(brief, s = null) {
  const text = String(brief || '');
  const parsed = parseMaybeJsonObject(text);
  let recommendation = normalizeLlmRecommendation(parsed?.recommendation || parsed?.llm_recommendation || parsed?.direction || parsed?.verdict || parsed?.action);
  if (!recommendation) {
    const structured = extractStructuredLine(text, [
      'LLM_RECOMMENDATION',
      'RECOMMENDATION',
      'DIRECTION',
      'LLM_DIRECTION',
      'VERDICT',
      'ВЕРДИКТ',
      'НАПРАВЛЕНИЕ',
      'РЕКОМЕНДАЦИЯ',
    ]);
    recommendation = normalizeLlmRecommendation(structured);
  }
  if (!recommendation) {
    const legacyLine = extractStructuredLine(text, ['ВЕРДИКТ', 'VERDICT', 'РЕШЕНИЕ']);
    if (/да[^\n]+подтверж/i.test(legacyLine) && ['long', 'short'].includes(String(s?.direction || '').toLowerCase())) {
      recommendation = String(s.direction).toUpperCase();
    } else {
      recommendation = normalizeLlmRecommendation(text);
    }
  }
  if (!recommendation) recommendation = 'NEUTRAL';
  return {
    recommendation,
    confidence: extractLlmConfidence(text, parsed),
    rationale: extractLlmRationale(text, parsed),
  };
}

function llmRecommendationTone(recommendation) {
  if (recommendation === 'LONG') return 'long';
  if (recommendation === 'SHORT') return 'short';
  if (recommendation === 'NEUTRAL') return 'neutral';
  return 'pending';
}

function llmMatchesAlgorithm(recommendation, s) {
  if (!s || !recommendation || recommendation === 'NEUTRAL') return null;
  const direction = String(s.direction || '').toUpperCase();
  return direction === recommendation;
}

function llmVerdictFor(s) {
  if (!s) {
    return {
      state: 'pending', tone: 'pending', recommendation: '—', label: 'WAITING', symbol: '—',
      confidence: null, confidenceText: '—', timeText: '—', updatedAt: null,
      summary: 'Выберите кандидата: здесь появится отдельная рекомендация LLM — LONG / SHORT / NEUTRAL.',
      meta: 'Фоновый LLM ещё не оценивал сетап.', rationale: '', agreement: null,
    };
  }
  const symbol = String(s.symbol || '—').toUpperCase();
  if (s.llm_status === 'running') {
    return {
      state: 'running', tone: 'pending', recommendation: '—', label: 'ANALYZING', symbol,
      confidence: null, confidenceText: '—', timeText: 'в процессе', updatedAt: s.llm_updated_at || null,
      summary: 'LLM-оценка выполняется в фоне.',
      meta: `${symbol} · ${s.interval || '—'} · ${s.llm_model || 'модель не указана'}`,
      rationale: '', agreement: null,
    };
  }
  if (s.llm_status === 'error') {
    return {
      state: 'error', tone: 'error', recommendation: '—', label: 'ERROR', symbol,
      confidence: null, confidenceText: '—', timeText: compactDateTime(s.llm_updated_at), updatedAt: s.llm_updated_at || null,
      summary: s.llm_error || 'LLM endpoint недоступен.',
      meta: `${symbol} · ошибка LLM · ${llmLifeText(s.llm_updated_at)}`,
      rationale: s.llm_error || '', agreement: null,
    };
  }
  if (s.llm_status === 'ok' && s.llm_brief) {
    const parsed = parseLlmBrief(s.llm_brief, s);
    const tone = llmRecommendationTone(parsed.recommendation);
    const confidenceText = parsed.confidence === null ? '—' : `${Math.round(parsed.confidence)}%`;
    const timeText = compactDateTime(s.llm_updated_at);
    const agreement = llmMatchesAlgorithm(parsed.recommendation, s);
    const directionText = parsed.recommendation === 'NEUTRAL'
      ? 'LLM рекомендует не открывать сделку без дополнительных подтверждений.'
      : `LLM рекомендует ${parsed.recommendation}.`;
    const agreementText = agreement === null ? '' : agreement ? ' Совпадает с направлением алгоритма.' : ' Не совпадает с направлением алгоритма.';
    return {
      state: 'ok', tone, recommendation: parsed.recommendation, label: parsed.recommendation, symbol,
      confidence: parsed.confidence, confidenceText, timeText, updatedAt: s.llm_updated_at || null,
      summary: `${directionText}${agreementText}`,
      meta: `Время verdict: ${timeText} · confidence ${confidenceText} · ${s.llm_model || 'LLM model n/a'} · ${llmLifeText(s.llm_updated_at)}`,
      rationale: parsed.rationale || 'LLM не передал краткое rationale.',
      agreement,
    };
  }
  return {
    state: 'pending', tone: 'pending', recommendation: '—', label: 'NO VERDICT', symbol,
    confidence: null, confidenceText: '—', timeText: '—', updatedAt: null,
    summary: 'LLM ещё не оценивал выбранный сетап.',
    meta: `${symbol} · LLM работает в фоне. LLM‑оценка появится автоматически после фонового цикла.`,
    rationale: '', agreement: null,
  };
}

function renderLlmVerdict(s) {
  const card = $('llmVerdictCard');
  if (!card) return;
  const verdict = llmVerdictFor(s);
  card.className = `llm-symbol-verdict ${cssToken(verdict.tone, 'pending')}`;
  setText('llmSymbolBox', `${verdict.symbol}`);
  setText('llmVerdictLabel', verdict.state === 'ok' ? 'LLM VERDICT' : verdict.label);
  setText('llmRecommendationLabel', verdict.recommendation);
  setText('llmConfidenceLabel', verdict.confidenceText);
  setText('llmTimeLabel', verdict.timeText);
  setText('llmVerdictText', verdict.rationale || verdict.summary);
  setText('llmVerdictMeta', verdict.meta);
}

function backtestEvidenceStatus(s) {
  const trades = num(s?.trades_count, 0);
  const pf = num(s?.profit_factor, null);
  const dd = num(s?.max_drawdown, null);
  if (!trades || trades <= 0 || pf === null || dd === null) return 'warn';
  if (trades >= 30 && pf >= 1.25 && dd <= 0.22) return 'pass';
  if (trades >= 10 && (pf < 0.90 || dd > 0.40)) return 'fail';
  return 'warn';
}

function backtestEvidenceTitle(s) {
  const trades = num(s?.trades_count, 0);
  const pf = num(s?.profit_factor, null);
  const dd = num(s?.max_drawdown, null);
  if (!trades || trades <= 0 || pf === null || dd === null) return 'Бэктест ожидается';
  return `Бэктест: ${fmt(trades, 0)} сделок, PF ${fmt(pf, 2)}, DD ${pct(dd, 1)}`;
}

function baseChecklistFor(s) {
  if (!s) return [];
  const rr = riskReward(s);
  const hasSpread = hasNumber(s.spread_pct);
  const spread = num(s.spread_pct, null);
  const confidence = num(s.confidence, 0);
  const liquidityKnown = s.is_eligible !== null && s.is_eligible !== undefined;
  const eligible = bool(s.is_eligible);
  const maxAgeHours = num(state.status?.max_signal_age_hours, 24) || 24;
  const serverFreshnessKnown = typeof s.fresh === 'boolean' || Boolean(s.data_status);
  const created = s.created_at ? new Date(s.created_at) : null;
  const createdStale = !created || Number.isNaN(created.getTime()) || Date.now() - created.getTime() > maxAgeHours * 3600_000;
  const stale = serverFreshnessKnown ? s.fresh !== true : createdStale;
  const freshnessTitle = stale
    ? (s.data_status === 'no_bar_time' ? 'Нет времени рыночной свечи' : s.data_status === 'unclosed_bar' ? 'Свеча не закрыта' : 'Сигнал устарел')
    : 'Сигнал свежий';
  const freshnessText = serverFreshnessKnown
    ? `Bar closed ${compactDateTime(s.bar_closed_at)}; age ${fmt(s.signal_age_minutes, 0)} мин. API freshness: ${escapeHtml(s.data_status || 'fresh')}.`
    : `Создан ${ageText(s.created_at)}. Максимальный возраст: ${maxAgeHours} ч.`;
  const spreadStatus = !hasSpread ? 'warn' : spread <= 0.08 ? 'pass' : spread <= 0.15 ? 'warn' : 'fail';
  const liquidityStatus = !liquidityKnown ? 'warn' : eligible ? 'pass' : 'fail';
  const backtestStatus = backtestEvidenceStatus(s);

  return [
    { key: 'freshness', status: stale ? 'fail' : 'pass', title: freshnessTitle, text: freshnessText },
    { key: 'direction', status: s.direction === 'long' || s.direction === 'short' ? 'pass' : 'fail', title: s.direction === 'long' || s.direction === 'short' ? 'Направление задано' : 'Нет направления сделки', text: `Направление: ${String(s.direction || 'flat').toUpperCase()}. Flat не является сделкой.` },
    { key: 'mtf', status: mtfSeverity(s), title: mtfSeverity(s) === 'pass' ? 'MTF согласован' : mtfSeverity(s) === 'warn' ? 'MTF неполный' : 'MTF запрещает вход', text: `${mtfLabel(s)}. ${s.mtf_reason || '15m — вход; 60m и 240m — фильтры, а не отдельные триггеры.'}` },
    { key: 'liquidity', status: liquidityStatus, title: liquidityStatus === 'pass' ? 'Ликвидность допущена' : liquidityStatus === 'warn' ? 'Ликвидность ожидает snapshot' : 'Ликвидность не допущена', text: `Liquidity score ${fmt(s.liquidity_score, 2)}, spread ${hasSpread ? pctRaw(spread, 4) : '—'}, turnover 24h ${fmt(s.turnover_24h, 1)} USDT.` },
    { key: 'spread', status: spreadStatus, title: spreadStatus === 'pass' ? 'Spread нормальный' : spreadStatus === 'warn' ? 'Spread требует контроля' : 'Spread слишком широкий', text: `Текущий spread ${hasSpread ? pctRaw(spread, 4) : '—'}. Чем шире spread, тем хуже исполнимость grid/бота.` },
    { key: 'rr', status: rr && rr.ratio >= 1.55 ? 'pass' : rr && rr.ratio >= 1.15 ? 'warn' : 'fail', title: rr ? `Risk/Reward ${rr.ratio.toFixed(2)}` : 'SL/TP невалидны', text: rr ? `Риск до SL ${pct(rr.riskPct, 2)}, потенциал до TP ${pct(rr.rewardPct, 2)}.` : 'Нельзя оценить сделку без entry, SL и TP.' },
    { key: 'confidence', status: confidence >= 0.62 ? 'pass' : confidence >= 0.52 ? 'warn' : 'fail', title: `Confidence ${pct(confidence, 0)}`, text: 'Низкая уверенность не запрещает анализ, но запрещает механический вход.' },
    { key: 'backtest', status: backtestStatus, title: backtestEvidenceTitle(s), text: backtestStatus === 'fail' ? 'Негативный бэктест снижает приоритет сетапа; это evidence-veto, а не MTF-veto.' : 'Малое число сделок или отсутствие свежего бэктеста снижает доказательность, но не скрывает сетап из очереди.' },
    { key: 'ml', status: mlEvidenceStatus(s), title: mlEvidenceTitle(s), text: mlEvidenceText(s) },
  ];
}

function noSignalExplanation() {
  const cycle = state.signalStatus?.last_cycle || {};
  const queued = num(cycle.queued, 0) || 0;
  const built = num(cycle.signals_built, 0) || 0;
  const failed = num(cycle.failed, 0) || 0;
  const synced = num(cycle.market_synced, 0) || 0;
  if (queued && synced && !built && !failed) {
    return `Рынок обновлен (${synced}/${queued}), но ни одна стратегия не дала entry-сетап на свежей закрытой свече. Это штатное WAIT-состояние, а не ошибка обучения ML.`;
  }
  if (failed) {
    return `Фоновый цикл завершился частично: ошибок ${failed}. Проверьте API/DB-журнал и last_cycle.`;
  }
  if (queued && !synced) {
    return 'Фоновый цикл запущен, но свежий рынок еще не загружен. Вход по умолчанию запрещён.';
  }
  return 'Обновите рынок и рекомендации. По умолчанию вход запрещён.';
}

function algorithmDecisionFor(s) {
  if (!s) {
    return { level: 'reject', label: 'НЕТ ВХОДА', score: 0, title: 'Нет выбранного сетапа', subtitle: noSignalExplanation() };
  }

  // Серверная классификация является канонической: она одинаково используется
  // в API, таблице и главной карточке. Frontend fallback ниже нужен только для
  // старых backend-сборок или аварийной деградации API-контракта.
  if (s.operator_action) {
    const level = cssToken(s.operator_level, s.operator_action === 'REVIEW_ENTRY' ? 'review' : s.operator_action === 'WAIT' ? 'watch' : 'reject');
    const score = Math.round(num(s.operator_score, 0) || 0);
    const hard = Array.isArray(s.operator_hard_reasons) ? s.operator_hard_reasons : [];
    const warnings = Array.isArray(s.operator_warnings) ? s.operator_warnings : [];
    const evidence = Array.isArray(s.operator_evidence_notes) ? s.operator_evidence_notes : [];
    const first = hard[0] || warnings[0] || evidence[0];
    const subtitle = level === 'review'
      ? `Сетап можно вынести на ручную проверку: score ${score}. ${evidence.length ? `Evidence notes: ${evidence.map((x) => x.title).slice(0, 2).join('; ')}.` : 'Критических veto нет.'}`
      : level === 'watch'
        ? `Ждать/наблюдать: ${first?.title || 'недостаточно совокупной доказательности'}; score ${score}.`
        : `Вход запрещён: ${first?.title || 'сработал защитный фильтр'}; score ${score}.`;
    return {
      level,
      label: s.operator_label || (level === 'review' ? 'РУЧНАЯ ПРОВЕРКА ВХОДА' : level === 'watch' ? 'НАБЛЮДАТЬ' : 'НЕТ ВХОДА'),
      score,
      title: `${s.symbol}: ${s.operator_label || 'решение рассчитано'}`,
      subtitle,
    };
  }

  const checks = baseChecklistFor(s);
  const hardStopKeys = new Set(['freshness', 'direction', 'mtf', 'liquidity', 'spread', 'rr', 'confidence']);
  const hardFails = checks.filter((item) => item.status === 'fail' && hardStopKeys.has(item.key));
  const warnings = checks.filter((item) => item.status === 'warn' || (item.status === 'fail' && !hardStopKeys.has(item.key)));
  const rr = riskReward(s);
  let score = 0;
  score += Math.max(0, Math.min(1, num(s.research_score, 0))) * 16;
  score += Math.max(0, Math.min(1, num(s.mtf_score, 0))) * 16;
  score += Math.max(0, Math.min(1, num(s.confidence, 0))) * 20;
  score += Math.max(0, Math.min(1, ((rr?.ratio || 0) - 1) / 1.5)) * 18;
  score += bool(s.is_eligible) ? 10 : 0;
  score += num(s.spread_pct, 999) <= 0.08 ? 8 : num(s.spread_pct, 999) <= 0.15 ? 3 : 0;
  score += Math.max(0, Math.min(1, num(s.trades_count, 0) / 50)) * 6;
  score += Math.max(0, Math.min(1, num(s.profit_factor, 0) / 2)) * 6;
  score += Math.max(0, Math.min(1, (num(s.roc_auc, 0.5) - 0.5) / 0.2)) * 5;
  score += Math.max(0, 1 - Math.min(1, num(s.max_drawdown, 0.4) / 0.35)) * 3;
  if (s.mtf_veto || s.higher_tf_conflict || s.mtf_status === 'context_only') score -= 30;
  score = Math.round(Math.max(0, Math.min(100, score)));

  if (hardFails.length) {
    return { level: 'reject', label: 'НЕТ ВХОДА', score, title: `${s.symbol}: вход запрещён`, subtitle: `Причина: ${hardFails[0].title}. Сетап можно только разобрать, но не передавать на создание бота.` };
  }
  if (num(s.confidence, 0) >= 0.58 && rr && rr.ratio >= 1.45 && score >= 56) {
    return { level: 'review', label: 'РУЧНАЯ ПРОВЕРКА ВХОДА', score, title: `${s.symbol}: можно вынести на ручную проверку`, subtitle: `Критических veto нет. ${warnings.length ? `Есть замечания: ${warnings.map((x) => x.title).slice(0, 2).join('; ')}.` : 'Дополнительные проверки ниже.'}` };
  }
  return { level: 'watch', label: 'НАБЛЮДАТЬ', score, title: `${s.symbol}: только наблюдение`, subtitle: `Нет критического запрета, но сетап пока слабый: ${warnings.map((x) => x.title).slice(0, 2).join('; ') || 'score ниже входного порога'}.` };
}

function checklistFor(s, options = {}) {
  const checks = baseChecklistFor(s);
  if (!s || options.includeLlm === false) return checks;
  const verdict = llmVerdictFor(s);
  checks.push({
    key: 'llm',
    status: s.llm_status === 'ok' ? (verdict.recommendation === 'NEUTRAL' ? 'warn' : verdict.agreement === false ? 'warn' : 'pass') : 'warn',
    title: s.llm_status === 'ok' ? `LLM: ${verdict.recommendation} · ${verdict.confidenceText}` : s.llm_status === 'running' ? 'LLM‑оценка выполняется' : 'LLM‑оценка ожидается',
    text: `${verdict.rationale || verdict.summary}. ${verdict.meta}.`,
  });
  return checks;
}

function decisionFor(s) {
  return algorithmDecisionFor(s);
}

function reasonItems(s) {
  if (!s) return [];
  const rationale = typeof s.rationale === 'object' && s.rationale !== null ? s.rationale : {};
  const reason = REASON_LABELS[rationale.reason] || rationale.reason || 'причина не раскрыта в сигнале';
  const rr = riskReward(s);
  return [
    {
      level: mtfSeverity(s) === 'pass' ? 'good' : mtfSeverity(s) === 'warn' ? 'warn' : 'bad',
      title: `MTF: ${mtfLabel(s)}`,
      text: `${s.mtf_reason || '15m/60m/240m согласованность не раскрыта.'} Score: ${fmt(s.mtf_score, 2)}.`,
    },
    {
      level: num(s.confidence, 0) >= 0.62 ? 'good' : num(s.confidence, 0) >= 0.54 ? 'warn' : 'bad',
      title: `Сигнал: ${STRATEGY_LABELS[s.strategy] || s.strategy || 'стратегия неизвестна'}`,
      text: `${reason}. Confidence: ${pct(s.confidence, 0)}.`,
    },
    {
      level: rr && rr.ratio >= 1.55 ? 'good' : rr && rr.ratio >= 1.15 ? 'warn' : 'bad',
      title: `Математика сделки: R/R ${rr ? rr.ratio.toFixed(2) : '—'}`,
      text: rr ? `Риск ${pct(rr.riskPct, 2)} против потенциала ${pct(rr.rewardPct, 2)}.` : 'Entry/SL/TP не позволяют оценить риск.',
    },
    {
      level: num(s.profit_factor, 0) >= 1.25 ? 'good' : 'warn',
      title: `Бэктест: PF ${fmt(s.profit_factor, 2)}, Sharpe ${fmt(s.sharpe, 2)}`,
      text: `Сделок ${fmt(s.trades_count, 0)}, win rate ${pct(s.win_rate, 0)}, max DD ${pct(s.max_drawdown, 1)}.`,
    },
    {
      level: mlEvidenceStatus(s) === 'pass' ? 'good' : mlEvidenceStatus(s) === 'warn' ? 'warn' : 'bad',
      title: `ML: ${mlEvidenceTitle(s)}`,
      text: `${mlEvidenceText(s)} Вероятность модели по последнему состоянию: ${pct(s.ml_probability, 0)}. ML — фильтр, а не самостоятельная причина входа.`,
    },
    {
      level: 'warn',
      title: `Sentiment ${fmt(s.sentiment_score, 3)}`,
      text: 'Sentiment учитывается как контекст. Он не заменяет цену, ликвидность и риск.',
    },
  ];
}

function operatorProtocol(s) {
  if (!s) return [];
  const d = decisionFor(s);
  return [
    {
      title: '1. Проверить запреты',
      text: d.level === 'reject' ? 'Есть красный пункт. Сделку не открывать.' : 'Красных пунктов нет, но желтые требуют ручной проверки.',
    },
    {
      title: '2. Сверить MTF-картину',
      text: '15m должен быть рабочим trigger. 60m не должен быть против направления, 240m не должен давать regime veto.',
    },
    {
      title: '3. Сверить график и стакан',
      text: 'Проверить, что цена не ушла от entry, spread не расширился, нет резкого гэпа или новостного импульса.',
    },
    {
      title: '4. Проверить риск портфеля',
      text: 'Не открывать сетап, если уже есть коррелированная позиция или дневной лимит риска исчерпан.',
    },
    {
      title: '5. Создавать бота только вручную',
      text: 'Система не создает бота автоматически. Entry, SL и TP копируются оператором только после проверки.',
    },
  ];
}

function isEntryRecommendation(item) {
  const entry = String(state.entryInterval || item?.mtf_entry_interval || '15').toUpperCase();
  const interval = String(item?.interval || '').toUpperCase();
  const direction = String(item?.direction || '').toLowerCase();
  return interval === entry
    && (direction === 'long' || direction === 'short')
    && item?.mtf_status !== 'context_only'
    && item?.mtf_action_class !== 'CONTEXT_ONLY'
    && item?.mtf_is_entry_candidate !== false;
}

function candidateSortValue(item) {
  const priority = { review: 3, watch: 2, reject: 1 };
  return [
    priority[item?.decision?.level] || 0,
    num(item?.decision?.score, 0),
    num(item?.confidence, 0),
    num(item?.profit_factor, 0),
    -num(item?.max_drawdown, 999),
    num(item?.win_rate, 0),
  ];
}

function compareCandidates(a, b) {
  const left = candidateSortValue(a);
  const right = candidateSortValue(b);
  for (let i = 0; i < left.length; i += 1) {
    const diff = right[i] - left[i];
    if (diff) return diff;
  }
  return String(a?.symbol || '').localeCompare(String(b?.symbol || ''));
}

function dedupeCandidatesByMarket(items) {
  const bestByMarket = new Map();
  items.forEach((item) => {
    const symbol = String(item?.symbol || '').toUpperCase().trim();
    if (!symbol) return;
    const key = `${symbol}|${String(item?.interval || item?.mtf_entry_interval || '').toUpperCase()}`;
    const current = bestByMarket.get(key);
    if (!current || compareCandidates(item, current) < 0) {
      bestByMarket.set(key, { ...item, variant_count: 1 });
      return;
    }
    current.variant_count = num(current.variant_count, 1) + 1;
  });
  return Array.from(bestByMarket.values());
}

function candidates() {
  // rank is the canonical operator queue: it already contains MTF, liquidity,
  // backtest, ML and LLM joins. Raw /signals/latest is only a fallback while
  // rank is unavailable; otherwise it can show "MTF: не рассчитан" for rows
  // that simply were not enriched on the frontend side.
  const source = state.rank.length ? state.rank.map(withLlmFields) : state.signals.map(enrichedSignal);
  const mapped = source
    .filter(isEntryRecommendation)
    .map((item) => ({ ...withLlmFields(item), decision: decisionFor(item) }));
  const unique = dedupeCandidatesByMarket(mapped);
  unique.sort(compareCandidates);
  return unique;
}

function selectedCandidate() {
  const list = candidates();
  if (state.selectedId !== null) {
    const found = list.find((s) => Number(s.id) === Number(state.selectedId));
    if (found) return found;
  }
  return list[0] || null;
}

function renderDecision() {
  const s = selectedCandidate();
  const d = decisionFor(s);
  const board = $('decisionBoard');
  if (board) board.className = `decision-board panel signal-card ${d.level}`;
  setText('decisionBadge', d.label);
  if ($('decisionBadge')) $('decisionBadge').className = `decision-badge ${d.level}`;
  setText('decisionTitle', s?.symbol || d.title);
  setText('decisionVerdict', d.level === 'review' ? 'Только ручная проверка' : d.label === 'НЕТ ВХОДА' ? 'Вход запрещён' : d.label);
  setText('decisionSubtitle', d.subtitle);
  setText('decisionScore', d.score);
  updateTopContext(s);
  renderDecisionMeters(s, d);
  renderExecutionMap(s);

  renderTicket(s);
  renderChecklist(s);
  renderReasons(s);
  renderProtocol(s);
  renderBrief(s);
  renderLlmVerdict(s);
  renderMtfMatrix(s);
  syncEquitySelectionNote(s);
}

function renderTicket(s) {
  if (!s) {
    $('ticketTitle').textContent = 'Сетап не выбран';
    $('ticketBody').className = 'ticket-body empty-state';
    $('ticketBody').textContent = 'Выберите кандидата из очереди слева.';
    return;
  }
  const rr = riskReward(s);
  const llmVerdict = llmVerdictFor(s);
  const directionClass = s.direction === 'long' ? 'long' : s.direction === 'short' ? 'short' : '';
  $('ticketTitle').textContent = `${s.symbol} · ${s.interval || '—'} · ${String(s.direction || 'flat').toUpperCase()} · ${STRATEGY_LABELS[s.strategy] || s.strategy || 'стратегия'}`;
  $('ticketBody').className = 'ticket-body';
  $('ticketBody').innerHTML = `
    <div class="ticket-main">
      <div class="metric direction ${directionClass}"><span>Direction</span><strong>${escapeHtml(String(s.direction || 'flat').toUpperCase())}</strong></div>
      <div class="metric"><span>Entry</span><strong>${priceFmt(s.entry)}</strong></div>
      <div class="metric"><span>Stop-loss</span><strong>${priceFmt(s.stop_loss)}</strong></div>
      <div class="metric"><span>Take-profit</span><strong>${priceFmt(s.take_profit)}</strong></div>
      <div class="metric"><span>Risk до SL</span><strong>${rr ? pct(rr.riskPct, 2) : '—'}</strong></div>
      <div class="metric"><span>Потенциал до TP</span><strong>${rr ? pct(rr.rewardPct, 2) : '—'}</strong></div>
      <div class="metric"><span>R/R</span><strong>${rr ? rr.ratio.toFixed(2) : '—'}</strong></div>
      <div class="metric"><span>Confidence</span><strong>${pct(s.confidence, 0)}</strong></div>
      <div class="metric"><span>MTF</span><strong>${escapeHtml(mtfLabel(s))}</strong></div>
      <div class="metric"><span>LLM</span><strong>${escapeHtml(llmStateText(s).replace('LLM: ', ''))}</strong></div>
    </div>
    <div class="execution-plan">
      <b>Исполнение:</b> только ручная проверка. Entry/SL/TP не являются торговым приказом; красный пункт отменяет сетап.
    </div>
    <section class="llm-detail-card ${escapeHtml(cssToken(llmVerdict.tone, 'pending'))}">
      <header><span>LLM verdict · ${escapeHtml(llmVerdict.symbol)}</span><strong>${escapeHtml(llmVerdict.recommendation)} · ${escapeHtml(llmVerdict.confidenceText)}</strong></header>
      <p>${escapeHtml(llmVerdict.rationale || llmVerdict.summary)}</p>
      <small>${escapeHtml(llmVerdict.meta)}</small>
    </section>`;
}

function renderChecklist(s) {
  const checks = checklistFor(s);
  const box = $('checklist');
  if (!checks.length) {
    box.className = 'checklist-list empty-state';
    box.textContent = 'Нет данных для проверки.';
    return;
  }
  box.className = 'checklist-list';
  box.innerHTML = checks.map((item) => `
    <div class="check-item ${item.status}">
      <span class="check-icon">${item.status === 'pass' ? '✓' : item.status === 'warn' ? '!' : '×'}</span>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></div>
    </div>`).join('');
}

function renderReasons(s) {
  const items = reasonItems(s);
  const box = $('reasonList');
  if (!items.length) {
    box.className = 'reason-list empty-state';
    box.textContent = 'Нет выбранного кандидата.';
    return;
  }
  box.className = 'reason-list';
  box.innerHTML = items.map((item) => `
    <div class="reason-item ${item.level}">
      <span class="check-icon">${item.level === 'good' ? '✓' : item.level === 'warn' ? '!' : '×'}</span>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></div>
    </div>`).join('');
}

function renderProtocol(s) {
  const items = operatorProtocol(s);
  const box = $('operatorProtocol');
  if (!items.length) {
    box.className = 'protocol-list empty-state';
    box.textContent = 'Нет выбранного кандидата.';
    return;
  }
  box.className = 'protocol-list';
  box.innerHTML = items.map((item) => `
    <div class="protocol-item">
      <span class="check-icon">•</span>
      <div><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></div>
    </div>`).join('');
}


function renderBrief(s) {
  const box = $('briefBox');
  if (!s) {
    box.textContent = 'Нет выбранного сетапа. LLM‑оценка запустится после появления кандидатов.';
    return;
  }
  const verdict = llmVerdictFor(s);
  box.textContent = `${verdict.symbol}
Recommendation: ${verdict.recommendation}
Confidence: ${verdict.confidenceText}
Verdict time: ${verdict.timeText}
Rationale: ${verdict.rationale || verdict.summary}
${verdict.meta}`;
}

function renderQueue() {
  const list = candidates();
  $("kpiSignals").textContent = list.length || "—";
  const queue = $('candidateQueue');
  const filtered = state.filter === 'all' ? list : list.filter((s) => s.decision.level === state.filter);
  if (!filtered.length) {
    queue.className = 'candidate-queue empty-state';
    queue.textContent = list.length ? 'В этом фильтре нет кандидатов.' : noSignalExplanation();
    renderDecision();
    renderRawTable(list);
    return;
  }
  queue.className = 'candidate-queue';
  const selectedId = selectedCandidate()?.id;
  const rawTotal = state.rank.length ? state.rank.filter(isEntryRecommendation).length : state.signals.filter(isEntryRecommendation).length;
  queue.innerHTML = filtered.map((s) => {
    const selected = Number(s.id) === Number(selectedId);
    const decisionLevel = cssToken(s.decision.level, 'reject');
    const label = escapeHtml(s.decision.label);
    const variants = num(s.variant_count, 1) > 1 ? ` · ${num(s.variant_count, 1)} вариантов` : '';
    return `
      <article class="candidate ${decisionLevel} ${selected ? 'selected' : ''}" data-id="${escapeHtml(s.id)}" role="button" tabindex="0" aria-label="${escapeHtml(s.symbol)} ${label}">
        <span class="candidate-star" aria-hidden="true">☆</span>
        <div class="candidate-copy">
          <span class="symbol">${escapeHtml(s.symbol)}</span>
          <span class="candidate-timeframe">${escapeHtml(s.interval || '—')}m${escapeHtml(variants)} · ${escapeHtml(s.data_status || 'fresh')}</span>
        </div>
        <span class="badge ${decisionLevel}">${label}</span>
        <span class="candidate-score">${s.decision.score}</span>
        <span class="candidate-chevron" aria-hidden="true">›</span>
      </article>`;
  }).join('');
  const moreButton = document.querySelector('.queue-more');
  if (moreButton) {
    const hiddenDuplicates = Math.max(0, rawTotal - list.length);
    moreButton.innerHTML = `${hiddenDuplicates ? `Уникальные рынки: ${list.length}; скрыто дублей: ${hiddenDuplicates}` : 'Открыть полный список'} <span>›</span>`;
  }
  queue.querySelectorAll('.candidate').forEach((card) => {
    const select = () => {
      const parsedId = Number(card.dataset.id);
      state.selectedId = Number.isFinite(parsedId) ? parsedId : null;
      renderQueue();
      renderDecision();
      refreshNews().catch((error) => log(`WARN refresh selected news: ${error.message}`));
    };
    card.addEventListener('click', select);
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });
  });
  renderDecision();
  renderRawTable(list);
}

function renderRawTable(list = candidates()) {
  const body = $('rawTable').querySelector('tbody');
  body.innerHTML = list.map((s) => {
    const rr = riskReward(s);
    return `<tr class="dir-${cssToken(s.direction, 'flat')}">
      <td>${escapeHtml(s.decision.label)}</td>
      <td>${escapeHtml(s.decision.score)}</td>
      <td>${escapeHtml(mtfLabel(s))}</td>
      <td>${escapeHtml(s.symbol)}</td>
      <td>${escapeHtml(s.interval || '—')}</td>
      <td>${escapeHtml(String(s.direction || 'flat').toUpperCase())}</td>
      <td>${escapeHtml(s.strategy || '—')}</td>
      <td>${pct(s.confidence, 0)}</td>
      <td>${rr ? rr.ratio.toFixed(2) : '—'}</td>
      <td>${fmt(s.profit_factor, 2)}</td>
      <td>${pct(s.max_drawdown, 1)}</td>
      <td>${pctRaw(s.spread_pct, 3)}</td>
      <td>${escapeHtml(`${llmVerdictFor(s).recommendation} ${llmVerdictFor(s).confidenceText}`)}</td>
    </tr>`;
  }).join('');
}

async function refreshStatus() {
  const data = await api('/api/status');
  state.status = data;
  $('statusBox').textContent = `DB · ${compactDateTime(data.db_time)}`;
  $('statusBox').className = 'status ok';
  $('kpiCandles').textContent = data.candles ?? '—';
  setText('lastUpdateChip', `Update ${compactDateTime(data.db_time || new Date())}`);
}


async function refreshSignalStatus() {
  try {
    const data = await api('/api/signals/background/status');
    state.signalStatus = data.status || null;
    const status = state.signalStatus || {};
    const cycle = status.last_cycle || {};
    const text = status.enabled
      ? `Signals · ${(status.intervals || []).join('/') || '—'} · +${cycle.signals_upserted ?? 0}`
      : 'Signals · OFF';
    $('signalStatusBox').textContent = status.last_error ? `Signals: ошибка · ${status.last_error}` : text;
    $('signalStatusBox').className = status.enabled && !status.last_error ? 'status ok' : 'status error';
  } catch (e) {
    $('signalStatusBox').textContent = 'Signals · error';
    $('signalStatusBox').className = 'status error';
  }
}

async function refreshBacktestStatus() {
  try {
    const data = await api('/api/backtest/background/status');
    state.backtestStatus = data.status || null;
    state.backtestSummary = data.summary || null;
    const status = state.backtestStatus || {};
    const summary = state.backtestSummary || {};
    const text = status.enabled
      ? `BT · ${summary.fresh_runs || 0}/${summary.total || 0} · ${compactDateTime(status.next_run_at)}`
      : 'BT · OFF';
    $('backtestStatusBox').textContent = text;
    $('backtestStatusBox').className = status.enabled && !status.last_error ? 'status ok' : 'status error';
  } catch (e) {
    $('backtestStatusBox').textContent = 'BT · error';
    $('backtestStatusBox').className = 'status error';
  }
}

async function refreshLlmStatus() {
  try {
    const data = await api('/api/llm/background/status');
    state.llmStatus = data.status || null;
    state.llmSummary = data.summary || null;
    const evals = await api('/api/llm/evaluations/latest?limit=100');
    state.llmEvaluations = evals.items || [];
    const status = state.llmStatus || {};
    const summary = state.llmSummary || {};
    const text = status.enabled
      ? `LLM · ${summary.ok || 0}/${summary.total || 0} · ${compactDateTime(status.next_run_at)}`
      : 'LLM · OFF';
    $('llmStatusBox').textContent = text;
    $('llmStatusBox').className = status.enabled && !status.last_error ? 'status ok' : 'status error';
  } catch (e) {
    $('llmStatusBox').textContent = `LLM · error`;
    $('llmStatusBox').className = 'status error';
  }
}

async function refreshUniverse() {
  const data = await api(`/api/symbols/universe/latest?category=${encodeURIComponent($('category').value)}&mode=${encodeURIComponent($('universeMode').value)}&limit=50`);
  state.universe = data.items || [];
  $('kpiUniverse').textContent = state.universe.length || '—';
}

async function refreshRank() {
  const data = await api(`/api/research/rank?category=${encodeURIComponent($('category').value)}&interval=${encodeURIComponent($('interval').value)}&limit=40`);
  state.entryInterval = data.entry_interval || state.entryInterval || '15';
  state.recommendationIntervals = data.recommendation_intervals || [state.entryInterval];
  state.contextIntervals = data.context_intervals || state.contextIntervals;
  state.rank = data.items || [];
  renderQueue();
}

async function refreshSignals() {
  const data = await api('/api/signals/latest?limit=80&entry_only=true');
  state.signals = data.signals || [];
  if (state.selectedId !== null && !state.signals.some((s) => Number(s.id) === Number(state.selectedId))) state.selectedId = null;
  renderQueue();
}

function drawEquity(curve) {
  const canvas = $('equityCanvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, '#0f172a');
  gradient.addColorStop(1, '#020617');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!curve || curve.length < 2) return;
  const vals = curve.map((p) => Number(p.equity)).filter(Number.isFinite);
  if (vals.length < 2) return;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const pad = 26;
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad + i * (canvas.height - pad * 2) / 4;
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(canvas.width - pad, y);
    ctx.stroke();
  }
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = pad + i * (canvas.width - pad * 2) / (vals.length - 1);
    const y = canvas.height - pad - ((v - min) / Math.max(max - min, 1e-9)) * (canvas.height - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#cbd5e1';
  ctx.font = '12px system-ui';
  ctx.fillText(`min ${fmt(min, 2)} · max ${fmt(max, 2)}`, pad, 18);
}

async function refreshEquity() {
  const data = await api('/api/equity/latest?limit=1');
  state.equityRun = data.runs?.[0] || null;
  if (!state.equityRun) {
    setText('equityMeta', 'нет equity curve');
    setEquitySource('Equity-кривая не найдена. График появится после ручного или фонового бэктеста.', 'neutral');
    return;
  }
  $('equityMeta').textContent = `${state.equityRun.symbol} · ${compactStrategy(state.equityRun.strategy)} · return ${pct(state.equityRun.total_return, 1)} · DD ${pct(state.equityRun.max_drawdown, 1)}`;
  drawEquity(state.equityRun.equity_curve);
  syncEquitySelectionNote(selectedCandidate());
}

async function refreshNews() {
  const sym = selectedCandidate()?.symbol || selectedSymbols()[0] || 'BTCUSDT';
  const data = await api(`/api/news/latest?symbol=${encodeURIComponent(sym)}&limit=6`);
  state.news = data.news || [];
  const box = $('newsList');
  if (!state.news.length) {
    box.className = 'news-list empty-state';
    box.textContent = 'Новостей пока нет.';
  } else {
    box.className = 'news-list';
    box.innerHTML = state.news.map((n) => {
      const url = safeExternalUrl(n.url);
      return `
      <div class="news-item">
        <b>${escapeHtml(n.title || 'Без заголовка')}</b>
        <p>${escapeHtml(n.source_domain || n.source || '')} · ${dt(n.published_at)} · score ${fmt(n.llm_score ?? n.sentiment_score, 3)}</p>
        ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Открыть источник</a>` : ''}
      </div>`;
    }).join('');
  }
  try {
    const s = await api(`/api/sentiment/summary?symbol=${encodeURIComponent(sym)}&limit=6`);
    const score = s.result?.score ?? s.result?.summary_score ?? null;
    const scoreText = score === null || score === undefined ? '—' : fmt(score, 3);
    $('sentimentSummary').textContent = score === null || score === undefined ? sym : `${sym}: ${scoreText}`;
    setText('marketSymbolBox', sym);
    setText('marketSentimentBox', scoreText);
    setText('marketNewsCountBox', String(state.news.length));
    setText('marketMoodBox', score === null || score === undefined ? 'ожидание' : score > 0.12 ? 'позитивный' : score < -0.12 ? 'негативный' : 'нейтральный');
  } catch (e) {
    $('sentimentSummary').textContent = 'sentiment недоступен';
    setText('marketSymbolBox', sym);
    setText('marketSentimentBox', 'н/д');
    setText('marketNewsCountBox', String(state.news.length));
    setText('marketMoodBox', 'недоступен');
  }
}

async function refreshAll() {
  showOperationStatus('Обновляю экран и статусы…', 'busy');
  try {
    await refreshStatus();
    await refreshSignalStatus();
    await refreshBacktestStatus();
    await refreshLlmStatus();
    const results = await Promise.allSettled([refreshUniverse(), refreshRank(), refreshSignals(), refreshEquity(), refreshNews()]);
    const failed = results.filter((r) => r.status === 'rejected');
    if (failed.length) {
      showOperationStatus(`Экран обновлен частично: ${failed.length} блока недоступны. Подробности в журнале.`, 'warn');
      failed.forEach((r) => log(`WARN refresh block: ${r.reason?.message || r.reason}`));
    } else {
      showOperationStatus('Экран обновлен. Данные актуализированы.', 'ok');
    }
  } catch (e) {
    $('statusBox').textContent = 'DB/API error';
    $('statusBox').className = 'status error';
    showOperationStatus(`Ошибка обновления: ${e.message}`, 'error');
    log(`ERROR refresh: ${e.message}`);
  }
}

function showBusySkip(title) {
  showOperationStatus(`Операция «${title}» пропущена: предыдущая еще выполняется.`, 'warn');
  log(`SKIP ${title}: предыдущая операция еще выполняется`);
  return null;
}

async function runOperation(title, fn) {
  if (document.body.classList.contains('is-busy')) {
    showBusySkip(title);
    if (document.body.classList.contains('is-busy')) return;
  }
  setBusy(true);
  showOperationStatus(`Выполняется: ${title}…`, 'busy');
  try {
    const result = await fn();
    log(title, result);
    showOperationStatus(`Готово: ${title}.`, 'ok');
    return result;
  } catch (e) {
    log(`ERROR ${title}: ${e.message}`);
    showOperationStatus(`Ошибка: ${title}. ${e.message}`, 'error');
    return null;
  } finally {
    setBusy(false);
  }
}

function bindControls() {
  $('refreshAllBtn').onclick = async () => runOperation('Обновление экрана', refreshAll);
  const refreshQueueBtn = $('refreshQueueBtn');
  if (refreshQueueBtn) refreshQueueBtn.onclick = async () => runOperation('Обновление очереди', async () => { await refreshRank(); await refreshSignals(); return { ok: true }; });

  $('syncUniverseBtn').onclick = async () => {
    await runOperation('Universe built', async () => {
      validateInputs();
      const data = await api('/api/symbols/universe/build', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, mode: $('universeMode').value, limit: 25, refresh: true }),
      });
      $('symbols').value = (data.result.symbols || []).slice(0, 15).join(',');
      await refreshUniverse();
      return data.result;
    });
  };

  $('syncMarketBtn').onclick = async () => {
    await runOperation('Загрузка рынка', async () => {
      validateInputs({ requireSymbols: true });
      const timeoutMs = marketSyncTimeoutMs();
      showOperationStatus(`Выполняется: загрузка рынка. Таймаут ${Math.round(timeoutMs / 60_000)} мин; для ускорения уменьшите символы, интервалы или дни истории.`, 'busy');
      const data = await api('/api/sync/market', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbols: selectedSymbols(), interval: primaryInterval(), intervals: intervals(), days: Number($('days').value) }),
      }, timeoutMs);
      await refreshStatus();
      return data.result;
    });
  };

  $('syncSentimentBtn').onclick = async () => {
    await runOperation('Sentiment synced', async () => {
      validateInputs({ requireSymbols: true });
      showOperationStatus('Выполняется: обновление sentiment. Источники ограничены короткими таймаутами.', 'busy');
      const data = await api('/api/sync/sentiment', {
        method: 'POST',
        body: JSON.stringify({ symbols: selectedSymbols(), days: 7, use_llm: false, category: $('category').value, interval: primaryInterval(), intervals: intervals() }),
      }, SENTIMENT_OPERATION_TIMEOUT_MS);
      await refreshNews();
      return data.result;
    });
  };

  $('buildSignalsBtn').onclick = async () => {
    await runOperation('Signals built', async () => {
      validateInputs({ requireSymbols: true });
      const data = await api('/api/signals/build', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbols: selectedSymbols(), interval: primaryInterval(), intervals: intervals() }),
      });
      await refreshRank();
      await refreshSignals();
      await api('/api/llm/background/run-now', { method: 'POST' });
      await refreshBacktestStatus();
      await refreshLlmStatus();
      await refreshNews();
      return data.result;
    });
  };

  $('rankBtn').onclick = async () => runOperation('Rank refreshed', refreshRank);

  $('backtestBtn').onclick = async () => {
    await runOperation('Backtest', async () => {
      const s = selectedCandidate();
      const sym = s?.symbol || selectedSymbols()[0] || 'BTCUSDT';
      const strategy = s?.strategy || $('strategy').value;
      validateInputs();
      const data = await api('/api/backtest/run', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbol: sym, interval: s?.interval || primaryInterval(), strategy, limit: 5000 }),
      });
      state.equityRun = { ...data.result, symbol: sym, strategy };
      $('equityMeta').textContent = `${sym} · ${compactStrategy(strategy)} · return ${pct(data.result.total_return, 1)} · DD ${pct(data.result.max_drawdown, 1)}`;
      drawEquity(data.result.equity_curve);
      setEquitySource(`Источник графика: ручной бэктест выбранного сетапа ${sym} · ${compactStrategy(strategy)}. Именно эта кнопка перерисовывает карту сделки.`, 'ok');
      await refreshRank();
      return data.result;
    });
  };

  $('backtestAutoBtn').onclick = async () => {
    await runOperation('Background backtest refresh requested', async () => {
      const data = await api('/api/backtest/background/run-now', { method: 'POST' });
      await refreshBacktestStatus();
      await refreshRank();
      return data.status;
    });
  };

  $('signalsAutoBtn').onclick = async () => {
    await runOperation('Background signal refresh requested', async () => {
      const data = await api('/api/signals/background/run-now', { method: 'POST' });
      await refreshSignalStatus();
      await refreshBacktestStatus();
      await refreshLlmStatus();
      return data.status;
    });
  };

  // ML training/prediction controls are intentionally not exposed in the main UI.
  // Models are maintained by signal-auto-refresher; /api/ml/* remains available
  // for API-level diagnostics and emergency one-off maintenance.

  $('briefBtn').onclick = async () => {
    setContextTab('llm');
    await runOperation('LLM background refresh requested', async () => {
      const data = await api('/api/llm/background/run-now', { method: 'POST' });
      await refreshLlmStatus();
      renderQueue();
      return data.status;
    });
  };

  document.querySelector('.queue-more')?.addEventListener('click', () => {
    openTechnicalDetails();
    scrollToElement('technicalDetails');
  });

  $('editSelectedBtn')?.addEventListener('click', () => {
    setOpsPanelOpen(true);
    scrollToElement('opsPanel');
    $('strategy')?.focus();
  });

  $('refreshTicketBtn')?.addEventListener('click', async () => {
    await runOperation('Обновление выбранного сетапа', async () => {
      await refreshRank();
      await refreshSignals();
      await refreshLlmStatus();
      await refreshNews();
      return { ok: true, selected: selectedCandidate()?.symbol || null };
    });
  });

  $('opsToggleBtn').addEventListener('click', toggleOpsPanel);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && $('opsPanel')?.classList.contains('open')) {
      setOpsPanelOpen(true);
    }
  });

  document.querySelectorAll('.context-tab').forEach((button) => {
    button.addEventListener('click', () => setContextTab(button.dataset.tab));
  });

  document.querySelectorAll('.filter').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.filter').forEach((b) => {
        const active = b === button;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      state.filter = button.dataset.filter;
      renderQueue();
    });
  });

  document.querySelectorAll('.nav-item[data-nav-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.dataset.navTarget;
      activateNav(button);
      if (target === 'help') {
        const dialog = $('helpDialog');
        if (dialog?.showModal) dialog.showModal();
        else showOperationStatus('Помощь: обновите данные, выберите кандидата, проверьте Risk/Evidence/LLM/News/Protocol.', 'neutral');
        return;
      }
      if (target === 'settings') {
        setOpsPanelOpen(true);
        scrollToElement('opsPanel');
        $('strategy')?.focus();
        return;
      }
      if (target === 'equityCanvas') openTechnicalDetails();
      if (target === 'operatorProtocol') setContextTab('protocol');
      if (target === 'opsPanel') setOpsPanelOpen(true);
      scrollToElement(target);
    });
  });

  $('navToggleBtn')?.addEventListener('click', () => {
    const frame = document.querySelector('.app-frame');
    const collapsed = !frame?.classList.contains('nav-collapsed');
    frame?.classList.toggle('nav-collapsed', collapsed);
    document.body.classList.toggle('nav-collapsed', collapsed);
    $('navToggleBtn').setAttribute('aria-pressed', collapsed ? 'true' : 'false');
    $('navToggleBtn').setAttribute('aria-label', collapsed ? 'Показать меню' : 'Свернуть меню');
  });
}

bindControls();
setContextTab(state.contextTab);
setOpsPanelOpen(true);

let autoRefreshInFlight = false;
async function refreshBackgroundTick() {
  if (autoRefreshInFlight || document.body.classList.contains('is-busy')) return;
  autoRefreshInFlight = true;
  try {
    await refreshSignalStatus();
    await refreshBacktestStatus();
    await refreshLlmStatus();
    await refreshRank();
    await refreshSignals();
  } catch (e) {
    log(`ERROR auto refresh: ${e.message}`);
  } finally {
    autoRefreshInFlight = false;
  }
}

refreshAll();
setInterval(refreshBackgroundTick, 30_000);
