const protocols = {
  v2: {
    meta: ['3 мира', '30 заданий на модель', '4 096 токенов на ответ'],
    categories: ['Перемещение', 'Маршрут', 'Квест'],
    rows: [
      ['DeepSeek Flash','12/12','12/12','6/6','30/30','0/30','10 / 10 / 10'],
      ['Qwen 27B','12/12','10/10','6/6','28/28','2/30','10 / 10 / 8'],
      ['Kimi K3','12/12','11/11','6/6','29/29','1/30','10 / 10 / 9']
    ],
    takeaway: 'Все полученные ответы верны. Три отсутствующих ответа — маршрутные задания с content=null и finish_reason=length: два у Qwen и один у Kimi.',
    intersection: 'Совместно завершённые одинаковые задания: DeepSeek–Qwen 28/30, DeepSeek–Kimi 29/30, Qwen–Kimi 27/30. На всех пересечениях оба ответа правильны.',
    tokens: [['DeepSeek Flash','19 144','36 412','35 303','55 556','30'],['Qwen 27B','17 950','42 197','41 685','60 147','31'],['Kimi K3','21 240','43 580','40 464','64 820','31']]
  },
  v3: {
    meta: ['2 мира', '24 задания на модель', '8 192 токена на ответ'],
    categories: ['Движение', 'Маршрут', 'Обмены'],
    rows: [
      ['DeepSeek Flash','8/8','8/8','8/8','24/24','0/24','12 / 12'],
      ['Qwen 27B','8/8','4/4','8/8','20/20','4/24','10 / 10'],
      ['Kimi K3','8/8','7/7','8/8','23/23','1/24','12 / 11']
    ],
    takeaway: 'Все полученные ответы верны. Пять отсутствующих ответов — маршрутные задания с content=null и finish_reason=length: четыре у Qwen и один у Kimi.',
    intersection: 'Совместно завершённые одинаковые задания: DeepSeek–Qwen 20/24, DeepSeek–Kimi 23/24, Qwen–Kimi 20/24. На всех пересечениях оба ответа правильны; в каждой паре представлены оба мира.',
    tokens: [['DeepSeek Flash','21 680','33 812','32 646','55 492','26'],['Qwen 27B','20 473','61 763','61 375','82 236','25'],['Kimi K3','22 888','55 134','50 895','78 022','24']]
  }
};
function render(key) {
  const p = protocols[key];
  document.querySelectorAll('[data-protocol]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.protocol === key)));
  document.getElementById('protocol-meta').innerHTML = p.meta.map(value => `<span>${value}</span>`).join('');
  p.categories.forEach((value, i) => document.getElementById(`col${i+1}`).textContent = value);
  document.getElementById('results-body').innerHTML = p.rows.map(row => `<tr><th scope="row">${row[0]}</th>${row.slice(1,6).map((value,i) => `<td${i===3?' class="total"':''}>${value}</td>`).join('')}</tr>`).join('');
  document.getElementById('takeaway').innerHTML = `<span class="takeaway-icon">✳</span><p><strong>Что видно в этом срезе.</strong> ${p.takeaway}</p>`;
  document.getElementById('details-content').innerHTML = `<p>${p.intersection}</p><p>Получено ответов по мирам: ${p.rows.map(row=>`${row[0]} — ${row[6]}`).join('; ')}.</p><div class="table-wrap"><table><thead><tr><th>Модель</th><th>Вход</th><th>Выход</th><th>Из них reasoning</th><th>Всего</th><th>Сохранённых попыток</th></tr></thead><tbody>${p.tokens.map(row=>`<tr><th scope="row">${row[0]}</th>${row.slice(1).map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p>Суммы включают сохранённые ответы с пустым content; usage присутствует во всех записях. Повторы и запросы без сохранённого usage могут быть учтены не полностью. Reasoning — часть выходных токенов, а не дополнительная сумма.</p>`;
}
document.querySelectorAll('[data-protocol]').forEach(button => button.addEventListener('click', () => render(button.dataset.protocol)));
render('v2');
