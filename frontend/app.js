const $ = (id) => document.getElementById(id);

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

function symbols() {
  return $('symbols').value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
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

function ageText(value) {
  if (!value) return 'нет времени';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'время не распознано';
  const minutes = Math.max(0, Math.round((Date.now() - d.getTime()) / 60_000));
  if (minutes < 60) return `${minutes} мин назад`;
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)} ч назад`;
  return `${(minutes / 1440).toFixed(1)} дн назад`;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
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
}

function log(title, obj) {
  const payload = obj ? `\n${JSON.stringify(obj, null, 2)}` : '';
  $('log').textContent = `[${new Date().toLocaleTimeString()}] ${title}${payload}\n\n${$('log').textContent}`;
}

function rankBySignal(signal) {
  return state.rank.find((r) => Number(r.id) === Number(signal.id))
    || state.rank.find((r) => r.symbol === signal.symbol && r.strategy === signal.strategy && r.direction === signal.direction)
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

function llmStateText(s) {
  if (!s) return 'LLM: нет сетапа';
  if (s.llm_status === 'ok') return `LLM: готово · ${ageText(s.llm_updated_at)}`;
  if (s.llm_status === 'running') return 'LLM: анализируется';
  if (s.llm_status === 'error') return `LLM: ошибка · ${escapeHtml(s.llm_error || 'см. журнал')}`;
  return 'LLM: ожидает фонового цикла';
}

function checklistFor(s) {
  if (!s) return [];
  const rr = riskReward(s);
  const spread = num(s.spread_pct, 999);
  const confidence = num(s.confidence, 0);
  const research = num(s.research_score, 0);
  const dd = num(s.max_drawdown, 0.99);
  const trades = num(s.trades_count, 0);
  const rocAuc = num(s.roc_auc, 0.5);
  const eligible = bool(s.is_eligible);
  const maxAgeHours = num(state.status?.max_signal_age_hours, 24) || 24;
  const created = s.created_at ? new Date(s.created_at) : null;
  const stale = !created || Number.isNaN(created.getTime()) || Date.now() - created.getTime() > maxAgeHours * 3600_000;

  return [
    {
      key: 'freshness',
      status: stale ? 'fail' : 'pass',
      title: stale ? 'Сигнал устарел' : 'Сигнал свежий',
      text: `Создан ${ageText(s.created_at)}. Максимальный возраст: ${maxAgeHours} ч.`,
    },
    {
      key: 'direction',
      status: s.direction === 'long' || s.direction === 'short' ? 'pass' : 'fail',
      title: s.direction === 'long' || s.direction === 'short' ? 'Направление задано' : 'Нет направления сделки',
      text: `Направление: ${String(s.direction || 'flat').toUpperCase()}. Flat не является сделкой.`,
    },
    {
      key: 'liquidity',
      status: eligible ? 'pass' : 'fail',
      title: eligible ? 'Ликвидность допущена' : 'Ликвидность не допущена',
      text: `Liquidity score ${fmt(s.liquidity_score, 2)}, spread ${pctRaw(spread, 4)}, turnover 24h ${fmt(s.turnover_24h, 1)} USDT.`,
    },
    {
      key: 'spread',
      status: spread <= 0.08 ? 'pass' : spread <= 0.15 ? 'warn' : 'fail',
      title: spread <= 0.08 ? 'Spread нормальный' : spread <= 0.15 ? 'Spread пограничный' : 'Spread слишком широкий',
      text: `Текущий spread ${pctRaw(spread, 4)}. Чем шире spread, тем хуже исполнимость grid/бота.`,
    },
    {
      key: 'rr',
      status: rr && rr.ratio >= 1.55 ? 'pass' : rr && rr.ratio >= 1.15 ? 'warn' : 'fail',
      title: rr ? `Risk/Reward ${rr.ratio.toFixed(2)}` : 'SL/TP невалидны',
      text: rr ? `Риск до SL ${pct(rr.riskPct, 2)}, потенциал до TP ${pct(rr.rewardPct, 2)}.` : 'Нельзя оценить сделку без entry, SL и TP.',
    },
    {
      key: 'confidence',
      status: confidence >= 0.62 ? 'pass' : confidence >= 0.54 ? 'warn' : 'fail',
      title: `Confidence ${pct(confidence, 0)}`,
      text: 'Низкая уверенность не запрещает анализ, но запрещает механический вход.',
    },
    {
      key: 'backtest',
      status: trades >= 30 && num(s.profit_factor, 0) >= 1.25 && dd <= 0.22 ? 'pass' : trades >= 10 ? 'warn' : 'fail',
      title: `Бэктест: ${fmt(trades, 0)} сделок, PF ${fmt(s.profit_factor, 2)}, DD ${pct(dd, 1)}`,
      text: 'Малое число сделок или высокий DD снижает доказательность сетапа.',
    },
    {
      key: 'ml',
      status: rocAuc >= 0.58 ? 'pass' : rocAuc >= 0.52 ? 'warn' : 'fail',
      title: `ML ROC AUC ${fmt(rocAuc, 3)}`,
      text: `Research score ${fmt(research, 3)}. AUC около 0.5 означает отсутствие ML-подтверждения.`,
    },
    {
      key: 'llm',
      status: s.llm_status === 'ok' ? 'pass' : 'warn',
      title: s.llm_status === 'ok' ? 'LLM‑оценка готова' : s.llm_status === 'running' ? 'LLM‑оценка выполняется' : 'LLM‑оценка ожидается',
      text: `${llmStateText(s)}. Фоновый LLM — независимый риск‑разбор, не торговый приказ.`,
    },
  ];
}

function decisionFor(s) {
  if (!s) {
    return {
      level: 'reject',
      label: 'НЕТ ВХОДА',
      score: 0,
      title: 'Нет выбранного сетапа',
      subtitle: 'Обновите данные и постройте рекомендации. По умолчанию вход запрещён.',
    };
  }
  const checks = checklistFor(s);
  const hardFails = checks.filter((item) => item.status === 'fail');
  const warnings = checks.filter((item) => item.status === 'warn');
  const rr = riskReward(s);
  let score = 0;
  score += Math.max(0, Math.min(1, num(s.research_score, 0))) * 22;
  score += Math.max(0, Math.min(1, num(s.confidence, 0))) * 18;
  score += Math.max(0, Math.min(1, ((rr?.ratio || 0) - 1) / 1.5)) * 15;
  score += bool(s.is_eligible) ? 10 : 0;
  score += num(s.spread_pct, 999) <= 0.08 ? 8 : num(s.spread_pct, 999) <= 0.15 ? 3 : 0;
  score += Math.max(0, Math.min(1, num(s.trades_count, 0) / 50)) * 8;
  score += Math.max(0, Math.min(1, num(s.profit_factor, 0) / 2)) * 8;
  score += Math.max(0, Math.min(1, (num(s.roc_auc, 0.5) - 0.5) / 0.2)) * 7;
  score += Math.max(0, 1 - Math.min(1, num(s.max_drawdown, 0.4) / 0.35)) * 4;
  score = Math.round(Math.max(0, Math.min(100, score)));

  if (hardFails.length) {
    return {
      level: 'reject',
      label: 'НЕТ ВХОДА',
      score,
      title: `${s.symbol}: вход запрещён`,
      subtitle: `Причина: ${hardFails[0].title}. Сетап можно только разобрать, но не передавать на создание бота.`,
    };
  }
  if (warnings.length || score < 70) {
    return {
      level: 'watch',
      label: 'НАБЛЮДАТЬ',
      score,
      title: `${s.symbol}: только наблюдение`,
      subtitle: `Нет критического запрета, но есть слабые места: ${warnings.map((x) => x.title).slice(0, 2).join('; ') || 'оценка допуска ниже порога'}.`,
    };
  }
  return {
    level: 'review',
    label: 'К ПРОВЕРКЕ',
    score,
    title: `${s.symbol}: можно передать на ручную проверку`,
    subtitle: 'Это не приказ на вход. Оператор обязан сверить стакан, новости, общий риск портфеля и параметры создаваемого бота.',
  };
}

function reasonItems(s) {
  if (!s) return [];
  const rationale = typeof s.rationale === 'object' && s.rationale !== null ? s.rationale : {};
  const reason = REASON_LABELS[rationale.reason] || rationale.reason || 'причина не раскрыта в сигнале';
  const rr = riskReward(s);
  return [
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
      level: num(s.roc_auc, 0.5) >= 0.58 ? 'good' : num(s.roc_auc, 0.5) >= 0.52 ? 'warn' : 'bad',
      title: `ML: ROC AUC ${fmt(s.roc_auc, 3)}`,
      text: `Вероятность модели по последнему состоянию: ${pct(s.ml_probability, 0)}. ML — фильтр, а не самостоятельная причина входа.`,
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
      title: '2. Сверить график и стакан',
      text: 'Проверить, что цена не ушла от entry, spread не расширился, нет резкого гэпа или новостного импульса.',
    },
    {
      title: '3. Проверить риск портфеля',
      text: 'Не открывать сетап, если уже есть коррелированная позиция или дневной лимит риска исчерпан.',
    },
    {
      title: '4. Создавать бота только вручную',
      text: 'Система не создает бота автоматически. Entry, SL и TP копируются оператором только после проверки.',
    },
  ];
}

function candidates() {
  const source = state.signals.length ? state.signals.map(enrichedSignal) : state.rank.map(withLlmFields);
  const mapped = source.map((item) => ({ ...withLlmFields(item), decision: decisionFor(item) }));
  mapped.sort((a, b) => {
    const priority = { review: 3, watch: 2, reject: 1 };
    const levelDiff = (priority[b.decision.level] || 0) - (priority[a.decision.level] || 0);
    if (levelDiff) return levelDiff;
    return (b.decision.score || 0) - (a.decision.score || 0);
  });
  return mapped;
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
  board.className = `decision-board panel ${d.level}`;
  $('decisionBadge').textContent = d.label;
  $('decisionTitle').textContent = d.title;
  $('decisionSubtitle').textContent = d.subtitle;
  $('decisionScore').textContent = d.score;

  renderTicket(s);
  renderChecklist(s);
  renderReasons(s);
  renderProtocol(s);
  renderBrief(s);
}

function renderTicket(s) {
  if (!s) {
    $('ticketTitle').textContent = 'Сетап не выбран';
    $('ticketBody').className = 'ticket-body empty-state';
    $('ticketBody').textContent = 'Выберите кандидата из очереди ниже.';
    return;
  }
  const rr = riskReward(s);
  const directionClass = s.direction === 'long' ? 'long' : s.direction === 'short' ? 'short' : '';
  $('ticketTitle').textContent = `${s.symbol} · ${String(s.direction || 'flat').toUpperCase()} · ${STRATEGY_LABELS[s.strategy] || s.strategy || 'стратегия'}`;
  $('ticketBody').className = 'ticket-body';
  $('ticketBody').innerHTML = `
    <div class="ticket-main">
      <div class="metric direction ${directionClass}"><span>Direction</span><strong>${escapeHtml(String(s.direction || 'flat').toUpperCase())}</strong></div>
      <div class="metric"><span>Entry</span><strong>${fmt(s.entry, 4)}</strong></div>
      <div class="metric"><span>Stop-loss</span><strong>${fmt(s.stop_loss, 4)}</strong></div>
      <div class="metric"><span>Take-profit</span><strong>${fmt(s.take_profit, 4)}</strong></div>
      <div class="metric"><span>Risk до SL</span><strong>${rr ? pct(rr.riskPct, 2) : '—'}</strong></div>
      <div class="metric"><span>Потенциал до TP</span><strong>${rr ? pct(rr.rewardPct, 2) : '—'}</strong></div>
      <div class="metric"><span>R/R</span><strong>${rr ? rr.ratio.toFixed(2) : '—'}</strong></div>
      <div class="metric"><span>Confidence</span><strong>${pct(s.confidence, 0)}</strong></div>
      <div class="metric"><span>LLM</span><strong>${escapeHtml(llmStateText(s).replace('LLM: ', ''))}</strong></div>
    </div>
    <div class="execution-plan">
      <b>Правило исполнения:</b> не входить по рынку автоматически. Проверить текущую цену относительно entry, актуальный spread, стакан и новости. Если цена уже ушла, spread расширился или появился красный пункт в чек‑листе — сетап отменяется.
    </div>`;
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
  if (s.llm_status === 'ok' && s.llm_brief) {
    box.textContent = `${llmStateText(s)}\n\n${s.llm_brief}`;
    return;
  }
  if (s.llm_status === 'running') {
    box.textContent = 'Фоновый LLM сейчас анализирует этот сетап. Экран обновляется автоматически.';
    return;
  }
  if (s.llm_status === 'error') {
    box.textContent = `Фоновая LLM‑оценка не получена: ${s.llm_error || 'ошибка LLM endpoint'}. Это не блокирует приложение, но сетап нельзя считать полностью разобранным.`;
    return;
  }
  box.textContent = 'LLM‑оценка ещё не готова. Фоновый сервис периодически берет top‑кандидатов из очереди и сохраняет вердикт без ручного запроса.';
}

function renderQueue() {
  const list = candidates();
  $('kpiSignals').textContent = state.signals.length || '—';
  const queue = $('candidateQueue');
  const filtered = state.filter === 'all' ? list : list.filter((s) => s.decision.level === state.filter);
  if (!filtered.length) {
    queue.className = 'candidate-queue empty-state';
    queue.textContent = list.length ? 'В этом фильтре нет кандидатов.' : 'Очередь появится после построения рекомендаций.';
    renderDecision();
    renderRawTable(list);
    return;
  }
  queue.className = 'candidate-queue';
  queue.innerHTML = filtered.map((s, index) => {
    const rr = riskReward(s);
    const selected = Number(s.id) === Number(selectedCandidate()?.id);
    return `
      <article class="candidate ${s.decision.level} ${selected ? 'selected' : ''}" data-id="${escapeHtml(s.id)}">
        <div class="candidate-head">
          <div>
            <div class="symbol">${escapeHtml(s.symbol)}</div>
            <div class="candidate-meta"><span class="direction-${escapeHtml(s.direction)}">${escapeHtml(String(s.direction || 'flat').toUpperCase())}</span> · ${escapeHtml(STRATEGY_LABELS[s.strategy] || s.strategy || 'стратегия')}</div>
          </div>
          <span class="badge ${s.decision.level}">${escapeHtml(s.decision.label)}</span>
        </div>
        <div class="candidate-line">
          <span class="chip">#<b>${index + 1}</b></span>
          <span class="chip">Score <b>${s.decision.score}</b></span>
          <span class="chip">Conf <b>${pct(s.confidence, 0)}</b></span>
          <span class="chip">R/R <b>${rr ? rr.ratio.toFixed(2) : '—'}</b></span>
          <span class="chip">Spread <b>${pctRaw(s.spread_pct, 3)}</b></span>
          <span class="chip">${escapeHtml(llmStateText(s))}</span>
        </div>
        <div class="candidate-meta">${escapeHtml(decisionFor(s).subtitle)}</div>
      </article>`;
  }).join('');
  queue.querySelectorAll('.candidate').forEach((card) => {
    card.addEventListener('click', () => {
      state.selectedId = Number(card.dataset.id);
      renderQueue();
      renderDecision();
    });
  });
  renderDecision();
  renderRawTable(list);
}

function renderRawTable(list = candidates()) {
  const body = $('rawTable').querySelector('tbody');
  body.innerHTML = list.map((s) => {
    const rr = riskReward(s);
    return `<tr>
      <td>${escapeHtml(s.decision.label)}</td>
      <td>${escapeHtml(s.decision.score)}</td>
      <td>${escapeHtml(s.symbol)}</td>
      <td>${escapeHtml(String(s.direction || 'flat').toUpperCase())}</td>
      <td>${escapeHtml(s.strategy || '—')}</td>
      <td>${pct(s.confidence, 0)}</td>
      <td>${rr ? rr.ratio.toFixed(2) : '—'}</td>
      <td>${fmt(s.profit_factor, 2)}</td>
      <td>${pct(s.max_drawdown, 1)}</td>
      <td>${pctRaw(s.spread_pct, 3)}</td>
      <td>${escapeHtml(s.llm_status || 'pending')}</td>
    </tr>`;
  }).join('');
}

async function refreshStatus() {
  const data = await api('/api/status');
  state.status = data;
  $('statusBox').textContent = `OK · DB ${data.db_time || '—'}`;
  $('statusBox').className = 'status ok';
  $('kpiCandles').textContent = data.candles ?? '—';
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
      ? `LLM: авто · ok ${summary.ok || 0}/${summary.total || 0} · след. ${dt(status.next_run_at)}`
      : 'LLM: авто выключен';
    $('llmStatusBox').textContent = text;
    $('llmStatusBox').className = status.enabled && !status.last_error ? 'status ok' : 'status error';
  } catch (e) {
    $('llmStatusBox').textContent = `LLM: статус недоступен`;
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
  state.rank = data.items || [];
  renderQueue();
}

async function refreshSignals() {
  const data = await api('/api/signals/latest?limit=80');
  state.signals = data.signals || [];
  if (state.selectedId !== null && !state.signals.some((s) => Number(s.id) === Number(state.selectedId))) state.selectedId = null;
  renderQueue();
}

function drawEquity(curve) {
  const canvas = $('equityCanvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#070c12';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!curve || curve.length < 2) return;
  const vals = curve.map((p) => Number(p.equity)).filter(Number.isFinite);
  if (vals.length < 2) return;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const pad = 26;
  ctx.strokeStyle = '#263345';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = pad + i * (canvas.height - pad * 2) / 4;
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(canvas.width - pad, y);
    ctx.stroke();
  }
  ctx.strokeStyle = '#82cfff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = pad + i * (canvas.width - pad * 2) / (vals.length - 1);
    const y = canvas.height - pad - ((v - min) / Math.max(max - min, 1e-9)) * (canvas.height - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#dce8f5';
  ctx.font = '12px system-ui';
  ctx.fillText(`min ${fmt(min, 2)} · max ${fmt(max, 2)}`, pad, 18);
}

async function refreshEquity() {
  const data = await api('/api/equity/latest?limit=1');
  state.equityRun = data.runs?.[0] || null;
  if (!state.equityRun) return;
  $('equityMeta').textContent = `${state.equityRun.symbol} · ${state.equityRun.strategy} · return ${pct(state.equityRun.total_return, 1)} · DD ${pct(state.equityRun.max_drawdown, 1)}`;
  drawEquity(state.equityRun.equity_curve);
}

async function refreshNews() {
  const sym = selectedCandidate()?.symbol || symbols()[0] || 'BTCUSDT';
  const data = await api(`/api/news/latest?symbol=${encodeURIComponent(sym)}&limit=6`);
  state.news = data.news || [];
  const box = $('newsList');
  if (!state.news.length) {
    box.className = 'news-list empty-state';
    box.textContent = 'Новостей пока нет.';
  } else {
    box.className = 'news-list';
    box.innerHTML = state.news.map((n) => `
      <div class="news-item">
        <b>${escapeHtml(n.title || 'Без заголовка')}</b>
        <p>${escapeHtml(n.source_domain || n.source || '')} · ${dt(n.published_at)} · score ${fmt(n.llm_score ?? n.sentiment_score, 3)}</p>
        ${n.url ? `<a href="${escapeHtml(n.url)}" target="_blank" rel="noreferrer">Открыть источник</a>` : ''}
      </div>`).join('');
  }
  try {
    const s = await api(`/api/sentiment/summary?symbol=${encodeURIComponent(sym)}&limit=6`);
    const score = s.result?.score ?? s.result?.summary_score ?? null;
    $('sentimentSummary').textContent = score === null || score === undefined ? sym : `${sym}: ${fmt(score, 3)}`;
  } catch (e) {
    $('sentimentSummary').textContent = 'sentiment недоступен';
  }
}

async function refreshAll() {
  try {
    await refreshStatus();
    await refreshLlmStatus();
    await Promise.allSettled([refreshUniverse(), refreshRank(), refreshSignals(), refreshEquity(), refreshNews()]);
  } catch (e) {
    $('statusBox').textContent = 'DB/API error';
    $('statusBox').className = 'status error';
    log(`ERROR refresh: ${e.message}`);
  }
}

async function runOperation(title, fn) {
  try {
    const result = await fn();
    log(title, result);
    return result;
  } catch (e) {
    log(`ERROR ${title}: ${e.message}`);
    throw e;
  }
}

function bindControls() {
  $('refreshAllBtn').onclick = refreshAll;

  $('syncUniverseBtn').onclick = async () => {
    await runOperation('Universe built', async () => {
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
    await runOperation('Market synced', async () => {
      const data = await api('/api/sync/market', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value, days: Number($('days').value) }),
      });
      await refreshStatus();
      return data.result;
    });
  };

  $('syncSentimentBtn').onclick = async () => {
    await runOperation('Sentiment synced', async () => {
      const data = await api('/api/sync/sentiment', {
        method: 'POST',
        body: JSON.stringify({ symbols: symbols(), days: 7, use_llm: false, category: $('category').value, interval: $('interval').value }),
      });
      await refreshNews();
      return data.result;
    });
  };

  $('buildSignalsBtn').onclick = async () => {
    await runOperation('Signals built', async () => {
      const data = await api('/api/signals/build', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbols: symbols(), interval: $('interval').value }),
      });
      await refreshRank();
      await refreshSignals();
      await api('/api/llm/background/run-now', { method: 'POST' });
      await refreshLlmStatus();
      await refreshNews();
      return data.result;
    });
  };

  $('rankBtn').onclick = async () => runOperation('Rank refreshed', refreshRank);

  $('backtestBtn').onclick = async () => {
    await runOperation('Backtest', async () => {
      const s = selectedCandidate();
      const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
      const strategy = s?.strategy || $('strategy').value;
      const data = await api('/api/backtest/run', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, strategy, limit: 5000 }),
      });
      drawEquity(data.result.equity_curve);
      await refreshRank();
      return data.result;
    });
  };

  $('trainBtn').onclick = async () => {
    await runOperation('ML trained', async () => {
      const s = selectedCandidate();
      const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
      const data = await api('/api/ml/train', {
        method: 'POST',
        body: JSON.stringify({ category: $('category').value, symbol: sym, interval: $('interval').value, horizon_bars: 12 }),
      });
      await refreshRank();
      return data.result;
    });
  };

  $('predictBtn').onclick = async () => {
    await runOperation('ML prediction', async () => {
      const s = selectedCandidate();
      const sym = s?.symbol || symbols()[0] || 'BTCUSDT';
      const data = await api(`/api/ml/predict/latest?symbol=${encodeURIComponent(sym)}&category=${encodeURIComponent($('category').value)}&interval=${encodeURIComponent($('interval').value)}&horizon_bars=12`);
      return data.result;
    });
  };

  $('briefBtn').onclick = async () => {
    await runOperation('LLM background refresh requested', async () => {
      const data = await api('/api/llm/background/run-now', { method: 'POST' });
      await refreshLlmStatus();
      renderQueue();
      return data.status;
    });
  };

  document.querySelectorAll('.filter').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.filter').forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      state.filter = button.dataset.filter;
      renderQueue();
    });
  });
}

bindControls();
refreshAll();
setInterval(async () => {
  try {
    await refreshLlmStatus();
    await refreshRank();
    await refreshSignals();
  } catch (e) {
    log(`ERROR auto refresh: ${e.message}`);
  }
}, 30_000);
