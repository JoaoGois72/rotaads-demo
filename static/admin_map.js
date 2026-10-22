/* Mapa administrativo; nunca expõe token do dispositivo ou dados a anunciantes. */
(() => {
  'use strict';
  const mapElement = document.getElementById('fleet-map');
  const listElement = document.getElementById('geo-device-list');
  const info = document.getElementById('geo-map-message');
  let map = null, vehicleLayer = null, zoneLayer = null, fitOnce = false;
  function text(id, value) { document.getElementById(id).textContent = String(value); }
  function initializeMap() {
    if (map) return true;
    if (typeof L === 'undefined') {
      info.textContent = 'Leaflet indisponível (sem ligação à internet?). Consulte os dados na tabela.';
      return false;
    }
    mapElement.replaceChildren();
    map = L.map(mapElement, {scrollWheelZoom:false}).setView([38.7223,-9.1393], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom:18, attribution:'© OpenStreetMap contributors'
    }).addTo(map);
    vehicleLayer = L.layerGroup().addTo(map);
    zoneLayer = L.layerGroup().addTo(map);
    return true;
  }
  const td = (row, value) => {
    const cell = document.createElement('td'); cell.textContent = String(value); row.appendChild(cell);
  };
  async function update() {
    try {
      const response = await fetch('/api/admin/mapa', {cache:'no-store'});
      if (!response.ok) throw new Error('Falha ao obter informações');
      const data = await response.json();
      text('geo-online', data.online);
      text('geo-located', data.com_gps);
      text('geo-zones', data.zonas.length);
      text('geo-time', data.atualizado_em.replace('T',' ').slice(0,19));
      listElement.replaceChildren();
      for (const d of data.dispositivos) {
        const row = document.createElement('tr');
        td(row,d.nome); td(row,d.parceiro||'—'); td(row,d.cidade||'—');
        td(row,d.online?'● Online':'Offline');
        td(row,d.gps_recente?`${d.lat.toFixed(5)}, ${d.lon.toFixed(5)} (±${Math.round(d.precisao_m||0)} m)`:'Sem GPS recente');
        td(row,d.ultimo_sinal?.replace('T',' ').slice(0,19)||'—');
        listElement.appendChild(row);
      }
      if (!data.dispositivos.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');cell.colSpan=6;cell.textContent='Nenhum tablet cadastrado.';row.appendChild(cell);listElement.appendChild(row);
      }
      if (!initializeMap()) return;
      vehicleLayer.clearLayers(); zoneLayer.clearLayers();
      const bounds=[];
      for (const z of data.zonas) {
        L.circle([z.latitude,z.longitude],{radius:z.raio_m,color:'#168b78',weight:2,fillOpacity:0.09})
          .bindPopup(`${escapeHtml(z.nome)} · raio ${z.raio_m} m`).addTo(zoneLayer);
        bounds.push([z.latitude,z.longitude]);
      }
      for (const d of data.dispositivos) {
        if (!d.online || !d.gps_recente) continue;
        L.circleMarker([d.lat,d.lon],{radius:9,color:'#164a85',fillColor:'#7fedb7',fillOpacity:1,weight:2})
          .bindPopup(`${escapeHtml(d.nome)}<br>${escapeHtml(d.parceiro||'')}<br>Precisão: ${Math.round(d.precisao_m||0)} m`).addTo(vehicleLayer);
        bounds.push([d.lat,d.lon]);
      }
      if (!fitOnce && bounds.length) {map.fitBounds(bounds,{padding:[35,35],maxZoom:13});fitOnce=true;}
      info.textContent=`${data.com_gps} tablet(s) localizados. Coordenadas apenas enquanto recentes (120 s).`;
    } catch(err) { info.textContent='Não foi possível atualizar o mapa. Tente entrar novamente na administração.'; }
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  update(); setInterval(update,15000);
})();
