/* RotaAds V1.2 — publicidade por zona, com GPS voluntário.
   Em tablets reais, geolocalização do navegador requer HTTPS (localhost no PC é exceção).
   Sem consentimento/GPS continuam a rodar as campanhas sem zonas atribuídas. */
(() => {
  'use strict';
  const token = window.PLAYER_CONFIG.token;
  const root = `/api/ecra/${encodeURIComponent(token)}`;
  const content = document.getElementById('content');
  const connection = document.getElementById('connection');
  const qrWrap = document.getElementById('qr-wrap');
  const qr = document.getElementById('qr');
  const fullscreenBtn = document.getElementById('fullscreen-btn');
  const gpsButton = document.getElementById('gps-button');
  const gpsState = document.getElementById('gps-state');
  let playlist = [], index = -1, currentId = null;
  let timer = null, playing = false, generation = 0;
  let wakeLock = null, watchId = null, consent = false;
  let location = null; // Apenas última posição, sem histórico no player.

  const setStatus = (text) => { connection.textContent = text; };
  const setGpsState = (text) => { gpsState.textContent = text; };
  const waiting = () => {
    clearTimeout(timer);
    generation += 1;
    currentId = null;
    playing = false;
    content.innerHTML = '<div class="screen-wait"><div class="screen-symbol">↗</div><h1>A aguardar anúncios</h1><p>Não há campanhas disponíveis nesta zona ou para este ecrã.</p></div>';
    qrWrap.style.display = 'none';
  };
  async function getPlaylist() {
    try {
      const response = await fetch(`${root}/playlist`, {cache: 'no-store'});
      if (!response.ok) throw new Error('Dispositivo sem acesso');
      const data = await response.json();
      playlist = data.campanhas || [];
      setStatus('● Ligado');
      if (!playlist.length) {
        if (playing || currentId !== null || !content.querySelector('.screen-wait')) waiting();
        return;
      }
      // Se saiu da zona atual, muda imediatamente para anúncio permitido.
      if (!playing || !playlist.some((c) => c.id === currentId)) {
        index = -1;
        next();
      }
    } catch (_) { setStatus('Sem rede — a tentar novamente'); }
  }
  function locationPayload() {
    const recent = location && Date.now() - location.timestamp <= 60000;
    return consent && recent
      ? {consentimento_gps:true, lat:location.lat, lon:location.lon, precisao_m:location.accuracy}
      : {};
  }
  async function heartbeat(extra = {}) {
    try {
      const response = await fetch(`${root}/sinal`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({...locationPayload(), ...extra})
      });
      if (!response.ok) throw new Error('Sinal rejeitado');
      setStatus('● Ligado');
    } catch (_) { setStatus('Falha de ligação'); }
  }
  function logPlay(id) {
    fetch(`${root}/exibicao`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({campanha_id:id})
    }).catch(() => {});
  }
  function clear() {
    clearTimeout(timer);
    content.replaceChildren();
    qrWrap.style.display = 'none';
  }
  function next() {
    if (!playlist.length) { waiting(); return; }
    playing = true;
    generation += 1;
    const myGeneration = generation;
    clear();
    index = (index + 1) % playlist.length;
    const item = playlist[index];
    currentId = item.id;
    if (item.qr) { qr.src = item.qr; qrWrap.style.display = 'block'; }
    if (item.tipo === 'video') {
      const video = document.createElement('video');
      video.src = item.media;
      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.preload = 'auto';
      video.controls = false;
      let logged = false;
      video.addEventListener('playing', () => {
        if (!logged && myGeneration === generation) { logged = true; logPlay(item.id); }
      });
      video.addEventListener('ended', () => { if (myGeneration === generation) next(); });
      video.addEventListener('error', () => {
        if (myGeneration === generation) { setStatus('Erro num vídeo'); timer = setTimeout(next, 3000); }
      });
      content.appendChild(video);
      video.play().catch(() => { if (myGeneration === generation) timer = setTimeout(next, 3000); });
      timer = setTimeout(() => { if (myGeneration === generation) next(); }, 10 * 60 * 1000);
    } else {
      const img = document.createElement('img');
      img.alt = item.nome;
      img.src = item.media;
      img.onload = () => {
        if (myGeneration !== generation) return;
        logPlay(item.id);
        timer = setTimeout(next, Math.max(5, Number(item.duracao) || 12) * 1000);
      };
      img.onerror = () => { if (myGeneration === generation) timer = setTimeout(next, 3000); };
      content.appendChild(img);
    }
  }
  async function wake() {
    try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); }
    catch (_) {}
  }
  function disableGps() {
    consent = false;
    location = null;
    if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    gpsButton.textContent = 'Ativar GPS';
    setGpsState('GPS desligado');
    heartbeat({consentimento_gps:false}).then(getPlaylist);
  }
  function enableGps() {
    if (!window.isSecureContext || !navigator.geolocation) {
      setGpsState('GPS requer HTTPS ou localhost e permissão do navegador');
      return;
    }
    consent = true;
    gpsButton.textContent = 'Desligar GPS';
    setGpsState('A obter localização…');
    watchId = navigator.geolocation.watchPosition(
      (position) => {
        if (!consent) return;
        const {latitude, longitude, accuracy} = position.coords;
        if (accuracy > 1500) { setGpsState('Precisão insuficiente (>1500 m)'); return; }
        location = {lat:latitude, lon:longitude, accuracy, timestamp:Date.now()};
        setGpsState(`GPS ativo · precisão ~${Math.round(accuracy)} m`);
        heartbeat().then(getPlaylist);
      },
      (error) => {
        setGpsState(error.code === 1 ? 'Permissão de localização negada' : 'GPS indisponível — verifique o dispositivo');
        disableGps();
      },
      {enableHighAccuracy:true, maximumAge:10000, timeout:20000}
    );
  }
  gpsButton.addEventListener('click', () => consent ? disableGps() : enableGps());
  fullscreenBtn.addEventListener('click', async () => {
    try { await document.documentElement.requestFullscreen(); await wake(); } catch (_) {}
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) wake(); });
  window.addEventListener('pagehide', () => {
    if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
  });
  heartbeat(); getPlaylist(); wake();
  setInterval(heartbeat, 30000);
  setInterval(getPlaylist, 20000);
})();
