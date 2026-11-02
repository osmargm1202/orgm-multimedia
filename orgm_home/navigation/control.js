async function(options) {
  if(!document.hasFocus() || document.visibilityState!=='visible')return {ok:false,error:'La página dejó de estar enfocada.'};
  if(options.hosts && !options.hosts.some(h=>location.protocol==='https:'&&(location.hostname===h||location.hostname.endsWith('.'+h))))return {ok:false,error:'Vuelve a la página del servicio.'};
  const visible = el => {
    const r=el.getBoundingClientRect(), s=getComputedStyle(el);
    return r.width>3 && r.height>3 && s.visibility!=='hidden' && s.display!=='none' && !el.closest('[inert],[aria-hidden="true"]') && !el.disabled;
  };
  const query = selectors => selectors.flatMap(s=>Array.from(document.querySelectorAll(s))).find(visible);
  const mark = el => {
    document.querySelectorAll('[data-orgm-selected]').forEach(e=>e.removeAttribute('data-orgm-selected'));
    if(!document.getElementById('orgm-navigation-style')) {
      const style=document.createElement('style');style.id='orgm-navigation-style';
      style.textContent='[data-orgm-selected]{outline:4px solid #8ec9ff!important;outline-offset:3px!important;scroll-margin:80px!important}';
      document.head.append(style);
    }
    el.setAttribute('data-orgm-selected','');el.focus({preventScroll:true});el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  };
  if(options.action==='search') {
    const el=query(options.search||[]);
    if(!el) return {ok:false,error:'No encontré el buscador. Su integración necesita actualizarse.'};
    mark(el);if(!el.matches('input,textarea,[contenteditable="true"]')) el.click();
    // SPAs often reveal their actual input after clicking a search button.
    for(let i=0;i<10;i++) {
      const input=query(['input[type="search"]','input[name="q"]','input[data-uia="search-box-input"]','input[placeholder*="Buscar"]','input[placeholder*="Search"]']);
      if(input){mark(input);break;}await new Promise(r=>setTimeout(r,100));
    }
    return {ok:true,mode:'search'};
  }
  if(options.action==='play') {
    const button=query(options.play||[]);
    if(button){button.click();return {ok:true,mode:'play'};}
    const video=Array.from(document.querySelectorAll('video,audio')).find(el=>el.readyState>0 && (el.tagName==='AUDIO'||visible(el)));
    if(!video)return {ok:false,error:'No encontré el reproductor. Abre primero un video; los reproductores en marcos requieren su integración.'};
    if(video.paused)await video.play();else video.pause();return {ok:true,mode:'play'};
  }
  const dialog=Array.from(document.querySelectorAll('[role="dialog"],dialog[open]')).filter(visible).at(-1);
  const scope=dialog||document;
  const selectors=[...(options.items||[]),'a[href]','button','input','select','textarea','[role="button"]','[role="link"]','[tabindex]'];
  const candidates=Array.from(new Set(selectors.flatMap(s=>Array.from(scope.querySelectorAll(s))))).filter(visible).filter(el=>el.getAttribute('tabindex')!=='-1').slice(0,2500);
  if(!candidates.length)return {ok:false,error:'Esta página no tiene elementos navegables.'};
  let current=scope.querySelector('[data-orgm-selected]') || document.activeElement;
  if(options.action==='ok') {
    if(!candidates.includes(current)) {mark(candidates[0]);return {ok:true,mode:'select'};}
    if(current.matches('input,textarea,select,[contenteditable="true"]')) {current.focus();return {ok:true,mode:'input'};}
    current.click();return {ok:true,mode:'activate'};
  }
  if(!candidates.includes(current)) {
    current=candidates.find(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.top<innerHeight&&r.left>=0&&r.left<innerWidth;}) || candidates[0];mark(current);return {ok:true,mode:'select'};
  }
  const origin=current.getBoundingClientRect(), ox=origin.x+origin.width/2, oy=origin.y+origin.height/2;
  const horizontal=['left','right'].includes(options.action), sign=['left','up'].includes(options.action)?-1:1;
  const scored=candidates.filter(el=>el!==current&&!el.contains(current)&&!current.contains(el)).map(el=>{
    const r=el.getBoundingClientRect(), dx=r.x+r.width/2-ox, dy=r.y+r.height/2-oy;
    const forward=(horizontal?dx:dy)*sign, cross=Math.abs(horizontal?dy:dx);
    return {el,forward,score:forward+cross*3};
  }).filter(c=>c.forward>3).sort((a,b)=>a.score-b.score);
  if(scored.length)mark(scored[0].el);
  return {ok:true,mode:scored.length?'select':'edge'};
}
