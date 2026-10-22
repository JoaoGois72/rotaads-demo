/* Relatório agregado por hora. Nenhuma coordenada individual é solicitada. */
(() => {
  'use strict';
  const holder = document.getElementById('hourly-v13');
  if (!holder) return;
  fetch(holder.dataset.url, {credentials:'same-origin', cache:'no-store'})
    .then((res) => { if (!res.ok) throw new Error('Indisponível'); return res.json(); })
    .then((data) => {
      const max = Math.max(1, ...data.horas.map(x => x.reproducoes));
      holder.replaceChildren();
      for (const item of data.horas) {
        const cell = document.createElement('div');
        cell.className = 'v13-hour-cell';
        cell.title = `${String(item.hora).padStart(2,'0')}:00 — ${item.reproducoes} reproduções`;
        const number = document.createElement('strong'); number.textContent = item.reproducoes;
        const bar = document.createElement('span'); bar.className = 'v13-hour-bar';
        bar.style.height = `${Math.max(3, item.reproducoes / max * 100)}%`;
        const hour = document.createElement('small'); hour.textContent = String(item.hora).padStart(2,'0');
        cell.append(number, bar, hour); holder.append(cell);
      }
    }).catch(() => { holder.textContent = 'Não foi possível carregar as métricas por hora.'; });
})();
