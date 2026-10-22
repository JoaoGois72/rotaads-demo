/* V1.3.1: gráfico SVG sem bibliotecas externas, com tabela acessível de fallback. */
(() => {
  'use strict';
  const host = document.getElementById('v131-trend');
  const source = document.getElementById('v131-data');
  if (!host || !source) return;
  let rows;
  try { rows = JSON.parse(source.textContent); } catch (_) { return; }
  if (!Array.isArray(rows) || !rows.length) return;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 900 280');
  svg.setAttribute('preserveAspectRatio','none');
  svg.setAttribute('role','presentation');
  const x0 = 48, x1 = 882, y0 = 22, y1 = 235;
  const max = Math.max(1, ...rows.flatMap(d=>[d.reproducoes,d.leituras,d.resgates]));
  const x = i=>x0+(x1-x0)*(i/Math.max(1,rows.length-1));
  const y = v=>y1-(y1-y0)*v/max;
  function element(tag,attrs,parent=svg,text){
    const node=document.createElementNS(ns,tag);
    Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));
    if (text!==undefined) node.textContent=text;
    parent.appendChild(node);return node;
  }
  for(let n=0;n<=4;n++){
    const value=Math.round(max*n/4), yy=y(max*n/4);
    element('line',{x1:x0,y1:yy,x2:x1,y2:yy,stroke:'#e6eef0','stroke-width':1});
    element('text',{x:40,y:yy+4,'text-anchor':'end',fill:'#688092','font-size':11},svg,value);
  }
  const colors={reproducoes:'#0f5067', leituras:'#46a887', resgates:'#c49442'};
  for(const key of Object.keys(colors)){
    const points=rows.map((r,i)=>`${x(i).toFixed(2)},${y(Number(r[key])||0).toFixed(2)}`).join(' ');
    const line=element('polyline',{points,fill:'none',stroke:colors[key], 'stroke-width':key==='reproducoes'?3:2.3,'stroke-linejoin':'round','stroke-linecap':'round'});
    element('title',{},line,`${key}: ${rows.reduce((n,r)=>n+(Number(r[key])||0),0)} eventos`);
  }
  const labels=[0,Math.floor((rows.length-1)/2),rows.length-1];
  for(const i of [...new Set(labels)]){
    element('text',{x:x(i),y:258,fill:'#6f8794','font-size':12,'text-anchor':i===0?'start':i===rows.length-1?'end':'middle'},svg,rows[i].data.slice(5));
  }
  host.replaceChildren(svg);
  // Não interromper impressão nem o uso em aba secundária.
  if(document.body.classList.contains('admin-body') && !location.pathname.endsWith('/imprimir')){
    window.setInterval(()=>{if(document.visibilityState==='visible' && !document.querySelector('details[open]')) location.reload();},60000);
  }
})();
