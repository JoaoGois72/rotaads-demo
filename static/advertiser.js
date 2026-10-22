/* Portal V1.1 — atualização periódica apenas de campanhas da sessão autenticada. */
(() => {
  'use strict';
  const root = document.getElementById('portal-main') || document.getElementById('campaign-detail');
  if (!root) return;
  const number = new Intl.NumberFormat('pt-PT');
  const val = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = typeof value === 'number' ? number.format(value) : (value ?? '—'); };
  const updateTime = t => {
    if (!t) return;
    try { val('updated-at', 'Atualizado às ' + new Date(t).toLocaleTimeString('pt-PT')); }
    catch(e) { val('updated-at', 'Atualizado recentemente'); }
  };
  function drawBars(days) {
    const el = document.getElementById('daily-chart');
    if (!el) return;
    el.replaceChildren();
    const max = Math.max(1, ...days.map(d => d.reproducoes || 0));
    for (const day of days) {
      const wrapper = document.createElement('div'); wrapper.className='chart-bar-wrap';
      const count = document.createElement('span'); count.className='chart-value'; count.textContent=number.format(day.reproducoes);
      const bar = document.createElement('div'); bar.className='chart-bar';
      bar.style.height = (Math.max(2,(day.reproducoes/max)*147))+'px';
      bar.title = `${day.dia}: ${day.reproducoes} reproduções iniciadas`;
      const label = document.createElement('span'); label.className='chart-label'; label.textContent=day.dia.slice(8)+'/'+day.dia.slice(5,7);
      wrapper.append(count,bar,label); el.append(wrapper);
    }
  }
  async function refresh() {
    if (document.hidden) return;
    try {
      const r=await fetch(root.dataset.liveUrl,{cache:'no-store',credentials:'same-origin'});
      if (r.status===401) { window.location.href='/anunciante/entrar'; return; }
      if (!r.ok) throw new Error('Servidor temporariamente indisponível');
      const data=await r.json();
      if (root.id==='portal-main') {
        val('stat-online',data.carros_online);
        val('stat-contracted',data.carros_contratados);
        val('stat-plays',data.reproducoes);
        val('stat-qr',data.leituras_qr);
        val('stat-redemptions',data.resgates);
        for (const c of data.campanhas) {
          const row=document.querySelector(`[data-campaign-id="${c.id}"]`);
          if (!row) continue;
          const put=(key,text)=>{const e=row.querySelector(`[data-field="${key}"]`);if(e)e.textContent=text;};
          put('estado',c.estado);put('carros_online',number.format(c.carros_online));
          put('attribution',`${c.carros_atribuidos} / ${c.carros_contratados}`);
          put('reproducoes',number.format(c.reproducoes));
          put('leituras_qr',c.qr_ativo?number.format(c.leituras_qr):'—');
          const pill=row.querySelector('[data-field="estado"]');
          if (pill) pill.className='pill '+(c.estado==='Em curso'?'good':'muted-pill');
        }
      } else {
        const m=data.metricas;
        val('detail-online',m.carros_online);val('detail-contracted',m.carros_contratados);
        val('detail-attributed',m.carros_atribuidos);val('detail-plays',m.reproducoes);
        val('detail-qr',m.qr_ativo?m.leituras_qr:'—');
        val('detail-redemptions',m.qr_ativo?m.resgates:'—');val('detail-status',m.estado);
        drawBars(data.diario || []);
      }
      updateTime(data.atualizado_em);
    } catch(e) { val('updated-at','Ligação indisponível · nova tentativa automática'); }
  }
  refresh(); setInterval(refresh,15000);
  document.addEventListener('visibilitychange',()=>{if (!document.hidden) refresh();});
})();

/* V1.2: relatório agregado por zona, sem localizações individuais. */
(async function loadGeoZones(){
 const element=document.getElementById('geo-zone-stats'); if(!element) return;
 try { const response=await fetch(element.dataset.url,{cache:'no-store'});if(!response.ok)throw Error('Não foi possível obter dados');
  const data=await response.json();element.replaceChildren();
  const rows=[...(data.zonas||[]),{nome:'Fora de zonas identificadas',reproducoes:data.sem_zona||0}];
  for(const z of rows){const line=document.createElement('div');line.className='geo-row';
   const name=document.createElement('span');name.textContent=z.nome;const n=document.createElement('strong');n.textContent=z.reproducoes.toLocaleString('pt-PT');
   line.append(name,n);element.appendChild(line);}
 } catch(_){element.textContent='Não foi possível obter as métricas geográficas.';}
})();
