'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let csrf = null;
let state = {session:false,capabilities:{}};
let busy = false;
let panel = 'sources';
let category = 'all';
let sessionSignature = '';
let switcherSignature = '';
let feedbackTimer;
let pairingDeadline=0;
let homeCursor=null;
let homeAppSelection=null;
const mobile = matchMedia('(max-width: 720px)');
const labels = Object.fromEntries($$('.app-tile[data-app]').map(button => [button.dataset.app, button.querySelector('.app-name').textContent]));
labels.home = 'ORGM Home';
const fragment = new URLSearchParams(location.hash.slice(1));
const kiosk = location.hostname === '127.0.0.1' && (fragment.has('pair') || sessionStorage.getItem('orgm-kiosk') === 'yes');
if (kiosk) { document.body.classList.add('is-kiosk'); sessionStorage.setItem('orgm-kiosk','yes'); $('.kiosk-hint').hidden = false; }
else { document.body.classList.add('is-controller'); panel='remote'; }
const defaultPanel=kiosk?'sources':'remote';
history.replaceState(null,'',location.pathname);
function feedback(message, error=false) {
  const element = $('#feedback'); element.textContent = message; element.classList.toggle('error',error); element.hidden=false;
  clearTimeout(feedbackTimer); feedbackTimer=setTimeout(()=>element.hidden=true, error ? 7500 : 3500);
}
async function api(path, body) {
  const options = {credentials:'same-origin',headers:{}};
  if (body !== undefined) { options.method='POST'; options.headers={'Content-Type':'application/json','X-CSRF-Token':csrf || ''}; options.body=JSON.stringify(body); }
  let response;
  try { response = await fetch(`/api/${path}`, options); } catch { throw new Error('No hay conexión con la sala. Comprueba la red.'); }
  let result;
  try { result = await response.json(); } catch { throw new Error('La sala no respondió. Vuelve a intentarlo.'); }
  if (!response.ok) {
    if (response.status===401 && path!=='session') { csrf=null; showPairing(); }
    throw new Error(typeof result.detail==='string' ? result.detail : 'Revisa los datos e inténtalo de nuevo.');
  }
  return result;
}
function showPanel(next) {
  panel=next;
  const paired=Boolean(csrf);
  for (const id of ['sources','remote','typing','settings']) {
    const visible=paired && (kiosk && next==='sources' ? ['sources','remote'].includes(id) : id===next);
    $(`#${id}`).hidden=!visible;
  }
  document.body.dataset.panel=next;
  $('#controller-nav').hidden=!paired || kiosk;
  $('#sessions').hidden=!paired || next!=='sources' || category!=='all';
  $('#music').hidden=!paired || next!=='sources' || !['all','music'].includes(category);
  filterSources();
  $$('[data-panel]').forEach(button=>{if(button.dataset.panel===next)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
}
function filterSources() {
  document.body.dataset.category=category;
  $$('.app-tile').forEach(button=>button.hidden=category!=='all' && button.dataset.category!==category);
  $$('.category-tabs button').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.category===category)));
  $('.side-nav [data-home]').setAttribute('aria-current',panel==='sources' && category==='all'?'page':'false');
  $('#source-title').textContent=category==='all'?'Todas las aplicaciones':$('.category-tabs [data-category='+category+'] span').textContent;
}
function settingsView(view='menu') {
  for(const name of ['menu','backgrounds','admin','cast'])$('#'+(name==='menu'?'settings-menu':name+'-view')).hidden=name!==view;
}
function showPairing() { $('#pairing').hidden=false; showPanel(panel); $('#connection-label').textContent='Sin vincular'; $('#connection').className='connection'; }
function render() {
  const online=Boolean(state.session);
  $('#connection-label').textContent=online ? 'Sala conectada' : 'Sala sin conexión';
  $('#connection').className=`connection ${online ? 'online' : 'error'}`;
  const active=labels[state.app] || 'Selecciona una aplicación';
  $('#remote-title').textContent=kiosk ? (state.app && state.app!=='home' ? active : 'Audio') : (online ? active : 'Mando');
  $('#remote-status').textContent=online ? (state.app==='home'?'Inicio está en la pantalla de Jarq':state.title || 'En la pantalla de Jarq') : (state.warning || 'Esperando conexión con Jarq');
  const backgroundMusic=state.audio_app==='spotify' && state.app!=='spotify';
  $('#current-label').textContent=online ? (backgroundMusic ? 'Spotify sigue sonando' : active) : 'La sala no está disponible';
  $('#current-detail').textContent=online ? (backgroundMusic ? 'La música continúa hasta que otra aplicación reproduzca audio.' : state.app==='home' ? 'Elige una aplicación para empezar.' : state.title || 'Lista para empezar') : (state.warning || 'Comprueba que el equipo esté encendido');
  $('#volume-value').textContent=state.volume===null || state.volume===undefined ? '—' : `${state.volume}%`;
  $('#mute').setAttribute('aria-pressed',String(Boolean(state.muted)));
  $('#mute').setAttribute('aria-label',state.muted ? 'Activar audio' : 'Silenciar audio');
  const song=state.spotify || {};
  $('#song-title').textContent=song.title || 'Elige música en Spotify';
  $('#song-artist').textContent=song.artist || (song.available ? 'Lista para reproducir' : 'Abre Spotify y elige una canción.');
  $('#music-title').textContent=song.playing ? 'Spotify está sonando' : 'Spotify';
  $$('[data-spotify]').forEach(button=>button.disabled=!online || busy || !song.available);
  $('#spotify-toggle').setAttribute('aria-label',song.playing?'Pausar Spotify':'Reproducir Spotify');
  $('#spotify-glyph').setAttribute('d',song.playing?'M7 4v16M17 4v16':'m8 4 12 8-12 8Z');
  renderSessions();
  if($('#app-switcher').open) renderSwitcher();
  $$('[data-close-app]').forEach(button=>button.disabled=!online || busy);
  document.body.dataset.background=state.background || 'costa';
  $$('button[data-background]').forEach(button=>{
    button.disabled=!online || busy;
    button.setAttribute('aria-pressed',String(button.dataset.background===state.background));
  });
  $$('[data-admin]').forEach(button=>button.disabled=!online || busy);
  $('#max-form button').disabled=!online || busy;
  $('#local-pairing').hidden=!kiosk;
  $('#generate-pair-code').disabled=!online || busy;
  $$('[data-app]').forEach(button=>{
    button.disabled=!online || busy;
    button.classList.toggle('is-active',button.dataset.app===state.app);
    button.classList.toggle('is-open',(state.open || []).includes(button.dataset.app));
    button.setAttribute('aria-pressed',String(button.dataset.app===state.app));
    button.setAttribute('aria-label',`${labels[button.dataset.app]}${button.dataset.app===state.app ? ', en pantalla' : (state.open || []).includes(button.dataset.app) ? ', abierta' : ''}`);
    const art=button.querySelector('.app-art');
    if(art){const id=button.dataset.app;const url=(state.open || []).includes(id) && state.previews?.[id] ? `/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}` : `/static/cards/${id}.png`;if(art.getAttribute('src')!==url)art.src=url;}
  });
  $$('[data-key]').forEach(button=>{const key=button.dataset.key; const capability=key==='mute' ? state.volume!==null : key==='play' ? state.capabilities?.play : state.capabilities?.keys && !(state.app==='home' && key==='backspace');button.disabled=!online || busy || !capability;});
  $$('[data-home],[data-volume],[data-switcher],#url-form button,#load-videos').forEach(button=>button.disabled=!online || busy);
  $('#text-form button[type=submit]').disabled=!online || busy || !state.capabilities?.text;
  $('#close-app').hidden=!state.capabilities?.close;
  $('#close-app').disabled=busy;
  $('#control-note').textContent=state.app==='home' ? 'Usa las flechas para elegir en la pantalla de Jarq y OK para abrir.' : state.app==='airplay' ? 'La reproducción se controla desde el dispositivo que transmite.' : 'En páginas web, Siguiente elemento mueve la selección y OK la abre. Usa Teclado para buscar.';
  if(kiosk && state.app && state.app!=='home')homeAppSelection=state.app;
}
function homeControls() {
  const scope=$('dialog[open]') || document;
  return [...scope.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled)')].filter(element=>element.getClientRects().length && getComputedStyle(element).visibility!=='hidden');
}
function selectHomeControl(element) {
  if(!element)return;
  $$('.home-selected').forEach(item=>item.classList.remove('home-selected'));
  homeCursor=element;
  if(element.matches('.app-tile[data-app]'))homeAppSelection=element.dataset.app;
  element.classList.add('home-selected');
  element.focus({preventScroll:true});
  element.scrollIntoView({block:'nearest',inline:'nearest'});
}
function focusHome(reset=false) {
  if(!kiosk || !csrf)return;
  if(reset){
    $$('dialog[open]').forEach(dialog=>dialog.close());
    category='all';showPanel('sources');
  }
  const controls=homeControls();
  const remembered=$$('.app-tile[data-app]').find(button=>button.dataset.app===homeAppSelection && controls.includes(button));
  const target=reset ? remembered : controls.includes(homeCursor)?homeCursor:null;
  selectHomeControl(target || controls.find(button=>button.classList.contains('app-tile')) || controls[0]);
}
function moveHomeSelection(key) {
  const controls=homeControls();
  const current=controls.includes(document.activeElement)?document.activeElement:controls.includes(homeCursor)?homeCursor:null;
  if(!current){focusHome();return;}
  const from=current.getBoundingClientRect(),horizontal=['ArrowLeft','ArrowRight'].includes(key),sign=['ArrowLeft','ArrowUp'].includes(key)?-1:1;
  const x=from.x+from.width/2,y=from.y+from.height/2;
  let next=null,best=Infinity;
  for(const candidate of controls){
    if(candidate===current)continue;
    const rect=candidate.getBoundingClientRect(),dx=rect.x+rect.width/2-x,dy=rect.y+rect.height/2-y;
    const forward=(horizontal?dx:dy)*sign,cross=Math.abs(horizontal?dy:dx);
    if(forward<1)continue;
    const score=forward+cross*2;
    if(score<best){best=score;next=candidate;}
  }
  selectHomeControl(next || current);
}
function renderSwitcher() {
  const opened=(state.open || []).filter(id=>id!=='home' && labels[id]);
  const signature=JSON.stringify([opened,state.app]);
  $('#switcher-empty').hidden=Boolean(opened.length);
  if(signature!==switcherSignature){
    switcherSignature=signature;
    const list=$('#switcher-list');list.replaceChildren();
    for(const id of opened){
      const row=document.createElement('div');row.className='switcher-row';
      const button=document.createElement('button');button.className='switcher-app';button.dataset.switchApp=id;
      button.setAttribute('aria-pressed',String(state.app===id));
      const image=document.createElement('img');image.alt='';
      const copy=document.createElement('span');copy.textContent=labels[id];
      const detail=document.createElement('small');detail.textContent=state.app===id?'En pantalla':'Cambiar a esta aplicación';copy.append(detail);
      button.append(image,copy);
      button.addEventListener('click',async()=>{
        if(await act(`apps/${id}/switch`)){$('#app-switcher').close();showPanel(defaultPanel);}
      });
      const close=document.createElement('button');close.className='switcher-remove';close.setAttribute('aria-label',`Cerrar ${labels[id]}`);
      const icon=document.createElement('img');icon.src='/static/icons/close.svg';icon.alt='';close.append(icon);
      close.addEventListener('click',async()=>{if(await act(`apps/${id}/close`,{},`${labels[id]} cerrada`))($('#switcher-list button') || $('#switcher-catalog')).focus();});
      row.append(button,close);list.append(row);
    }
  }
  $$('#switcher-list [data-switch-app]').forEach(button=>{
    const id=button.dataset.switchApp;
    const url=state.previews?.[id]?`/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}`:`/static/cards/${id}.png`;
    if(button.querySelector('img').getAttribute('src')!==url)button.querySelector('img').src=url;
  });
  $$('#switcher-list button').forEach(button=>button.disabled=busy || !state.session);
}
function renderSessions() {
  const opened=(state.open || []).filter(id=>id!=='home' && labels[id]);
  const signature=JSON.stringify(opened);
  if(signature===sessionSignature){
    $$('#session-grid [data-app]').forEach(button=>{const id=button.dataset.app;if(state.previews?.[id]){const url=`/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}`;if(button.querySelector('img').getAttribute('src')!==url)button.querySelector('img').src=url;button.querySelector('.session-hint').textContent='Captura reciente';}});
    return;
  }
  sessionSignature=signature;
  const grid=$('#session-grid');grid.replaceChildren();
  $('#sessions-empty').hidden=Boolean(opened.length);
  $('#session-count').textContent=opened.length ? `${opened.length} abiertas` : '';
  for(const id of opened){
    const card=document.createElement('div');card.className='session-item';
    const button=document.createElement('button');button.className='session-card';button.dataset.app=id;
    const image=document.createElement('img');image.alt='';image.src=state.previews?.[id]?`/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}`:`/static/cards/${id}.png`;
    const caption=document.createElement('span');caption.className='session-caption';caption.textContent=labels[id];
    const hint=document.createElement('span');hint.className='session-hint';hint.textContent=state.previews?.[id]?'Captura reciente':'Abierta';
    button.append(image,caption,hint);button.setAttribute('aria-label',`Volver a ${labels[id]}`);
    button.addEventListener('click',()=>selectApp(id,button));
    const close=document.createElement('button');close.className='session-close';close.dataset.closeApp=id;close.type='button';
    close.setAttribute('aria-label',`Cerrar ${labels[id]}`);close.title=`Cerrar ${labels[id]}`;
    const icon=document.createElement('img');icon.src='/static/icons/close.svg';icon.alt='';close.append(icon);
    close.addEventListener('click',async()=>{
      const index=opened.indexOf(id);
      if(await act(`apps/${id}/close`,{},`${labels[id]} cerrada`)){
        const remaining=$$('#session-grid [data-close-app]');
        (remaining[Math.min(index,remaining.length-1)] || $('.side-nav [data-home]')).focus({preventScroll:true});
      }
    });
    card.append(button,close);grid.append(card);
  }
}
async function refresh() {
  if (!csrf || busy) return;
  try { state=await api('status'); render(); } catch(error) {state.session=false;render();if(csrf) $('#current-detail').textContent=error.message;}
}
async function act(path, body={}, message='') {
  if(busy) return;
  busy=true; render();
  try {const result=await api(path,body);if(result.warning) feedback(result.warning,true);else if(message) feedback(message);return result;}
  catch(error){feedback(error.message,true);}
  finally{busy=false;await refresh();render();}
}
async function selectApp(id,button) {
  button.setAttribute('aria-busy','true');
  const result=await act(`apps/${id}/activate`,{},kiosk?`Abriendo ${labels[id]}`:'');
  button.removeAttribute('aria-busy');
  if(result && !kiosk) {
    if(id==='videos'){showPanel('typing');$('#load-videos').click();}
    else showPanel(defaultPanel);
  }
}
$$('[data-app]').forEach(button=>button.addEventListener('click',()=>selectApp(button.dataset.app,button)));
$$('.category-tabs button').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category;showPanel('sources');$('.app-grid').scrollLeft=0;}));
$$('.category-tabs button').forEach((button,index)=>button.addEventListener('keydown',event=>{if(!['ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const tabs=$$('.category-tabs button');const next=tabs[(index+(event.key==='ArrowDown'?1:-1)+tabs.length)%tabs.length];next.focus();next.click();}));
$$('[data-panel]').forEach(button=>button.addEventListener('click',()=>{if(button.dataset.panel==='settings')settingsView();showPanel(button.dataset.panel);}));
$$('[data-return]').forEach(button=>button.addEventListener('click',()=>showPanel(defaultPanel)));
$$('[data-switcher]').forEach(button=>button.addEventListener('click',()=>{renderSwitcher();$('#app-switcher').showModal();}));
$('#switcher-close').addEventListener('click',()=>$('#app-switcher').close());
$('#switcher-catalog').addEventListener('click',()=>{$('#app-switcher').close();showPanel('sources');});
$$('[data-settings-view]').forEach(button=>button.addEventListener('click',()=>settingsView(button.dataset.settingsView)));
$$('[data-key]').forEach(button=>button.addEventListener('click',()=>act('remote/key',{key:button.dataset.key})));
$$('[data-home]').forEach(button=>button.addEventListener('click',async()=>{await act('remote/home');category='all';showPanel(defaultPanel);if(kiosk)focusHome(true);else $('.app-grid').scrollLeft=0;}));
$$('[data-volume]').forEach(button=>button.addEventListener('click',()=>act('audio/volume',{delta:Number(button.dataset.volume)})));
$('#close-app').addEventListener('click',()=>act('remote/close',{},'Página cerrada'));
$$('[data-wifi]').forEach(button=>button.addEventListener('click',()=>act('wifi/open',{},'Wi-Fi abierto en la pantalla de Jarq')));
$$('[data-spotify]').forEach(button=>button.addEventListener('click',()=>act('spotify/'+button.dataset.spotify)));
$$('button[data-background]').forEach(button=>button.addEventListener('click',()=>act('preferences/background',{id:button.dataset.background})));
$$('[data-admin]').forEach(button=>button.addEventListener('click',()=>{
  const action=button.dataset.admin;
  if(action==='reboot') $('#reboot-confirm').showModal();
  else act(action==='rotate'?'display/rotate':'admin/restart-launcher',{},action==='rotate'?'Pantalla girada':'Reiniciando el launcher');
}));
$('#reboot-cancel').addEventListener('click',()=>$('#reboot-confirm').close());
$('#reboot-accept').addEventListener('click',()=>{$('#reboot-confirm').close();act('admin/reboot',{},'Reiniciando Jarq');});
$('#text-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('remote/text',{text:$('#remote-text').value},'Texto enviado'))$('#remote-text').value='';});
$('#url-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('browser/open-url',{url:$('#web-url').value},'Página abierta'))showPanel(defaultPanel);});
$('#max-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('apps/max/open-url',{url:$('#max-url').value},'Enlace abierto en Max')){$('#max-url').value='';showPanel(defaultPanel);}});
$('#generate-pair-code').addEventListener('click',async()=>{
  const result=await act('pairing/code');
  if(result){$('#pair-code').textContent=result.code;$('#pair-code').hidden=false;pairingDeadline=Date.now()+result.expires_in*1000;pairingClock();}
});
function pairingClock(){
  if(!pairingDeadline)return;
  const seconds=Math.max(0,Math.ceil((pairingDeadline-Date.now())/1000));
  $('#pair-code-time').textContent=seconds?`Caduca en ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}. Se usa una vez.`:'Código vencido. Genera otro.';
  if(!seconds){pairingDeadline=0;$('#pair-code').textContent='';$('#pair-code').hidden=true;}
}
setInterval(pairingClock,1000);
$('#load-videos').addEventListener('click',async()=>{
  try {const data=await api('videos');$('#video-list').replaceChildren();
    if(!data.files.length){const item=document.createElement('li');item.textContent='Todavía no hay archivos en Videos.';$('#video-list').append(item);}
    for(const name of data.files){const item=document.createElement('li'),button=document.createElement('button');button.textContent=name;button.addEventListener('click',async()=>{if(await act('videos/play',{name}))showPanel(defaultPanel);});item.append(button);$('#video-list').append(item);}
  } catch(error){feedback(error.message,true);}
});
$('#pair-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#pair-form button');button.disabled=true;
  try {const result=await api('session',{token:$('#pair-token').value.trim()});csrf=result.csrf;$('#pair-token').value='';$('#pairing').hidden=true;showPanel(defaultPanel);await refresh();}
  catch(error){feedback(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener('keydown',event=>{
  if(kiosk || !csrf || busy || $('#app-switcher').open || event.ctrlKey || event.metaKey || event.altKey || ['INPUT','TEXTAREA','BUTTON','A'].includes(event.target.tagName))return;
  const key={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'ok',Escape:'back'}[event.key];
  if(key && state.capabilities?.keys){event.preventDefault();act('remote/key',{key});}
  if(event.key==='Home'){event.preventDefault();act('remote/home');showPanel(defaultPanel);}
});
if(kiosk){
  $('.app-grid').removeAttribute('tabindex');
  document.addEventListener('focusin',event=>{
    if(homeControls().includes(event.target)){
      $$('.home-selected').forEach(item=>item.classList.remove('home-selected'));
      homeCursor=event.target;homeCursor.classList.add('home-selected');
      if(homeCursor.matches('.app-tile[data-app]'))homeAppSelection=homeCursor.dataset.app;
    }
  });
  document.addEventListener('keydown',event=>{
    if(!csrf || busy || event.ctrlKey || event.metaKey || event.altKey)return;
    if(event.key==='Home'){event.preventDefault();event.stopImmediatePropagation();focusHome(true);return;}
    if(event.target.matches('input,textarea,select,[contenteditable=true]'))return;
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){
      event.preventDefault();event.stopImmediatePropagation();moveHomeSelection(event.key);
    }else if(event.key==='Enter'){
      event.preventDefault();event.stopImmediatePropagation();
      if(!homeControls().includes(document.activeElement))focusHome();
      if(document.activeElement instanceof HTMLButtonElement)document.activeElement.click();
    }else if(event.key==='Escape' && !$('dialog[open]')){
      event.preventDefault();event.stopImmediatePropagation();
      if(panel==='settings' && !$('#settings-menu').hidden){focusHome(true);}
      else if(panel==='settings'){settingsView();selectHomeControl($('#settings-menu button'));}
      else focusHome(true);
    }
  },true);
}
mobile.addEventListener('change',()=>showPanel(panel));
function clock(){const now=new Date();$('#clock').textContent=now.toLocaleTimeString('es-DO',{hour:'2-digit',minute:'2-digit',hour12:false});$('#calendar').textContent=now.toLocaleDateString('es-DO',{weekday:'short',day:'numeric',month:'short'});}
clock();setInterval(clock,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
async function start() {
  showPanel(defaultPanel);
  try {const token=fragment.get('pair'); const result=token ? await api('session',{token}) : await api('session');fragment.delete('pair');csrf=result.csrf;$('#pairing').hidden=true;showPanel(defaultPanel);await refresh();if(kiosk)focusHome();}
  catch(error){fragment.delete('pair');showPairing();if(kiosk)feedback(error.message,true);}
  setInterval(()=>{if(!document.hidden)refresh();},3000);
}
start();
