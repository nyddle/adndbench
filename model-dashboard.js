(() => {
  'use strict';
  const data = window.ADND_MODEL_DATA;
  if (!data || !Array.isArray(data.scenarios)) return;
  const split = document.getElementById('model-split');
  const scenarioSelect = document.getElementById('model-scenario');
  const modelFilter = document.getElementById('model-filter');
  const context = document.getElementById('model-context');
  const cards = document.getElementById('model-cards');
  if (!split || !scenarioSelect || !modelFilter || !context || !cards) return;
  const names = {'gpt-6-luna':'GPT-6 Luna','gpt-6.2-sol':'GPT-6.2 Sol','gpt-6.2-astra':'GPT-6.2 Astra'};
  const outcomes = {completed:'Завершено успешно',incorrect_answer:'Неверный ответ',turn_limit:'Игровой лимит ходов',defeat:'Поражение',dead_end:'Тупик',incorrect_code:'Неверный код',death:'Гибель',combat_limit:'Лимит боя'};
  const statuses = {action_limit:'Внешний лимит действий',technical_error:'Сбой протокола',pending:'Не запускалась',ready:'Не завершена',inflight:'Выполняется'};
  const started = e => e.status !== 'pending' && (e.status !== 'ready' || (e.result && e.result.turns > 0));
  const esc = v => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = v => v === null || v === undefined ? '—' : esc(v);
  const decimal = v => typeof v === 'number' && Number.isFinite(v) ? new Intl.NumberFormat('ru-RU', {maximumFractionDigits:2}).format(v) : '—';
  const scenarios = data.scenarios;
  const scenarioLabel = s => `${s.label || s.axis} · ${s.level || ''}`;
  const metric = (label, value) => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
  function battle(r,s) {
    if (s.axis === 'tactics') return r.terminal_reason === 'completed' ? '1 · победа' : r.terminal_reason === 'defeat' ? '1 · поражение' : '1 · не завершён';
    if (s.axis !== 'radical-adventure') return null;
    if (s.game_config && (s.game_config.combat === 'off' || s.game_config.combat === false)) return 'Не предусмотрен';
    if (!r.combat_status) return 'Не начат';
    const result = {victory:'победа',defeat:'поражение',ongoing:'в процессе'}[r.combat_status] || r.combat_status;
    return `1 · ${esc(result)}${r.combat_rounds != null ? `, раундов: ${num(r.combat_rounds)}` : ''}`;
  }
  function episode(e,s) {
    const r = e.result || {};
    let outcome = e.status === 'completed' ? (outcomes[r.terminal_reason] || r.terminal_reason || 'Завершено') : (statuses[e.status] || 'Не завершена');
    if (s.measurement === 'party_choice_feasible_by_oracle' && e.status === 'completed') outcome = r.terminal_reason === 'completed' ? 'Состав позволяет победить' : 'Победная стратегия не найдена';
    const b = battle(r,s);
    const metrics = [metric('Ходы',num(r.turns)), metric('Ошибки действий',num(r.invalid_actions))];
    if (r.completed_tasks != null) metrics.push(metric('Квестовые этапы',num(r.completed_tasks)));
    if (r.rooms_visited != null) metrics.push(metric('Комнаты',`${num(r.rooms_visited)}${r.rooms_total != null ? ` / ${num(r.rooms_total)}` : ''}`));
    if (r.recruited_count != null) metrics.push(metric('Спутники',num(r.recruited_count)));
    if (r.selected != null) metrics.push(metric('Выбор спутника',esc(({mage:'Маг',medic:'Лекарь',warden:'Страж'})[r.selected] || r.selected)));
    if (b !== null) metrics.push(metric('Бои',b));
    if (r.damage_dealt != null) metrics.push(metric('Нанесено урона',num(r.damage_dealt)));
    if (r.healing != null) metrics.push(metric('Исцеление',num(r.healing)));
    if (r.charges_used != null) metrics.push(metric('Потрачено зарядов',num(r.charges_used)));
    if (r.hero_hp != null) metrics.push(metric('Здоровье героя',num(r.hero_hp)));
    if (e.score != null && e.status === 'completed') {
      metrics.push(metric('Балл',`${decimal(e.score)} / 100`));
      if (e.score_version === 'radical-efficiency-score-0.2.0' && e.score_breakdown) {
        const progress = e.score_breakdown.progress || {};
        const efficiency = e.score_breakdown.efficiency || {};
        metrics.push(metric('Прогресс',`${decimal(progress.earned)} / ${decimal(progress.weight)}`));
        metrics.push(metric('Эффективность',`${decimal(efficiency.earned)} / ${decimal(efficiency.weight)}`));
      }
    }
    const info = e.status !== 'completed' ? ' partial' : (r.terminal_reason === 'completed' ? '' : ' failed');
    return `<article class="model-episode${info}"><div class="episode-top"><span>${s.fixed_case ? 'Фиксированный случай' : `Мир ${num(e.world)}`}</span><strong>${esc(outcome)}</strong></div><dl>${metrics.join('')}</dl></article>`;
  }
  function render() {
    const s = scenarioSelect.selectedIndex < 0 ? null : scenarios[Number(scenarioSelect.value)];
    if (!s) { cards.innerHTML = '<p class="model-empty">Для этой выборки результатов пока нет.</p>'; context.textContent = ''; return; }
    const list = modelFilter.value === 'all' ? Object.keys(names) : [modelFilter.value];
    const trials = s.episodes.filter(started);
    const worlds = new Set(trials.map(e => e.world)).size;
    const plannedWorlds = new Set(s.episodes.map(e => e.world)).size;
    const splitLabel = s.split === 'holdout' ? 'отложенная проверка' : 'исследовательский набор';
    let notes = `${splitLabel} · ${s.fixed_case ? 'фиксированный случай' : `миров начато ${worlds} / запланировано ${plannedWorlds}`} · Codex · effort ${s.effort || '—'} · лимит ${s.max_actions || '—'} действий`;
    if (data.updated_at) notes += ` · снимок ${data.updated_at}`;
    if (s.axis === 'radical-adventure') {
      notes += ' · баллы только за завершённые партии';
      if (s.game_config && s.game_config.max_turns) notes += ` · игровой лимит ${s.game_config.max_turns} ходов`;
      if (s.episodes.some(e => e.score_version === 'radical-efficiency-score-0.2.0')) notes += ' · шкала v0.2';
    }
    if (s.measurement === 'party_choice_feasible_by_oracle') notes += ' · успех выбора = существование победной стратегии, а не сыгранный бой';
    if (s.axis === 'memory-compact') notes += ' · история доступна в контексте';
    if (s.execution_note) notes += ` · ${s.execution_note}`;
    context.textContent = notes;
    cards.innerHTML = list.map(model => {
      const planned = s.episodes.filter(e => e.model === model);
      const episodes = planned.filter(started);
      const done = episodes.filter(e => e.status === 'completed');
      const success = done.filter(e => e.result && e.result.terminal_reason === 'completed').length;
      const successSummary = done.length ? `Успехов ${success} / ${done.length} завершено` : 'Нет завершённых партий';
      const summary = s.measurement === 'party_choice_feasible_by_oracle' ? `Завершено ${done.length} / ${planned.length} запланировано` : `Завершено ${done.length} / ${planned.length} запланировано · ${successSummary}`;
      return `<section class="model-card"><div class="model-card-head"><h3>${esc(names[model])}</h3><span>${planned.length ? esc(summary) : 'Нет данных'}</span></div>${episodes.length ? episodes.map(e=>episode(e,s)).join('') : '<p class="model-empty">На этом испытании модель не запускалась.</p>'}</section>`;
    }).join('');
  }
  function rebuild() {
    const previous = scenarioSelect.selectedIndex < 0 ? null : scenarios[Number(scenarioSelect.value)];
    scenarioSelect.innerHTML = '';
    scenarios.forEach((s,i) => {
      if (s.split !== split.value || !s.episodes.some(started)) return;
      const option = document.createElement('option'); option.value = i; option.textContent = scenarioLabel(s); scenarioSelect.appendChild(option);
    });
    const candidates = Array.from(scenarioSelect.options);
    const preferred = candidates.find(o => previous && scenarios[Number(o.value)].label === previous.label) || candidates.find(o => scenarios[Number(o.value)].axis === 'radical-adventure') || candidates[0];
    if (preferred) scenarioSelect.value = preferred.value;
    render();
  }
  split.addEventListener('change',rebuild);
  scenarioSelect.addEventListener('change',render);
  modelFilter.addEventListener('change',render);
  rebuild();
})();
