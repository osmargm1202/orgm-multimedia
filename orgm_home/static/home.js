'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let csrf = null;
let state = {session:false,capabilities:{}};
let busy = false;
let panel = 'sources';
let category = 'all';
let sessionSignature = '';
let feedbackTimer;
const mobile = matchMedia('(max-width: 720px)');
const labels = Object.fromEntries($$('.app-tile[data-app]').map(button => [button.dataset.app, button.querySelector('.app-name').textContent]));
labels.home = 'ORGM Home';
const fragment = new URLSearchParams(location.hash.slice(1));
const kiosk = location.hostname === '127.0.0.1' && (fragment.has('pair') || sessionStorage.getItem('orgm-kiosk') === 'yes');
if (kiosk) { document.body.classList.add('is-kiosk'); sessionStorage.setItem('orgm-kiosk','yes'); $('.kiosk-hint').hidden = false; }
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
    const visible=paired && (next==='sources' ? ['sources','remote'].includes(id) : id===next);
    $(`#${id}`).hidden=!visible;
  }
  document.body.dataset.panel=next;
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
  for(const name of ['menu','backgrounds','admin'])$('#'+(name==='menu'?'settings-menu':name+'-view')).hidden=name!==view;
}
function showPairing() { $('#pairing').hidden=false; showPanel(panel); $('#connection-label').textContent='Sin vincular'; $('#connection').className='connection'; }
function render() {
  const online=Boolean(state.session);
  $('#connection-label').textContent=online ? 'Sala conectada' : 'Sala sin conexión';
  $('#connection').className=`connection ${online ? 'online' : 'error'}`;
  const active=labels[state.app] || 'Selecciona una aplicación';
  $('#remote-title').textContent=state.app && state.app!=='home' ? active : 'Audio';
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
  document.body.dataset.background=state.background || 'costa';
  $$('button[data-background]').forEach(button=>{
    button.disabled=!online || busy;
    button.setAttribute('aria-pressed',String(button.dataset.background===state.background));
  });
  $$('[data-admin]').forEach(button=>button.disabled=!online || busy);
  $$('[data-app]').forEach(button=>{
    button.disabled=!online || busy;
    button.classList.toggle('is-active',button.dataset.app===state.app);
    button.classList.toggle('is-open',(state.open || []).includes(button.dataset.app));
    button.setAttribute('aria-pressed',String(button.dataset.app===state.app));
    button.setAttribute('aria-label',`${labels[button.dataset.app]}${button.dataset.app===state.app ? ', en pantalla' : (state.open || []).includes(button.dataset.app) ? ', abierta' : ''}`);
    const art=button.querySelector('.app-art');
    if(art){const id=button.dataset.app;const url=(state.open || []).includes(id) && state.previews?.[id] ? `/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}` : `/static/cards/${id}.png`;if(art.getAttribute('src')!==url)art.src=url;}
  });
  $$('[data-key]').forEach(button=>{const key=button.dataset.key; const capability=key==='mute' ? state.volume!==null : key==='play' ? state.capabilities?.play : state.capabilities?.keys;button.disabled=!online || busy || !capability;});
  $$('[data-home],[data-volume],#url-form button,#load-videos').forEach(button=>button.disabled=!online || busy);
  $('#text-form button[type=submit]').disabled=!online || busy || !state.capabilities?.text;
  $('#close-app').hidden=!state.capabilities?.close;
  $('#close-app').disabled=busy;
  $('#control-note').textContent=state.app==='home' ? 'Abre una aplicación para usar el mando.' : state.app==='spotify' ? 'Controla la música desde Spotify.' : ['netflix','max','crunchyroll','browser'].includes(state.app) ? 'Las teclas dependen de la página. Usa Teclado para búsquedas.' : 'Los controles dependen de cada aplicación.';
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
    const button=document.createElement('button');button.className='session-card';button.dataset.app=id;
    const image=document.createElement('img');image.alt='';image.src=state.previews?.[id]?`/api/previews/${encodeURIComponent(id)}?v=${state.previews[id]}`:`/static/cards/${id}.png`;
    const caption=document.createElement('span');caption.className='session-caption';caption.textContent=labels[id];
    const hint=document.createElement('span');hint.className='session-hint';hint.textContent=state.previews?.[id]?'Captura reciente':'Abierta';
    button.append(image,caption,hint);button.setAttribute('aria-label',`Volver a ${labels[id]}`);
    button.addEventListener('click',()=>selectApp(id,button));grid.append(button);
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
  const result=await act(`apps/${id}/activate`,{},`Abriendo ${labels[id]}`);
  button.removeAttribute('aria-busy');
  if(result && !kiosk) {
    if(id==='videos'){showPanel('typing');$('#load-videos').click();}
    else showPanel('sources');
  }
}
$$('[data-app]').forEach(button=>button.addEventListener('click',()=>selectApp(button.dataset.app,button)));
$$('.category-tabs button').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category;showPanel('sources');$('.app-grid').scrollLeft=0;}));
$$('.category-tabs button').forEach((button,index)=>button.addEventListener('keydown',event=>{if(!['ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const tabs=$$('.category-tabs button');const next=tabs[(index+(event.key==='ArrowDown'?1:-1)+tabs.length)%tabs.length];next.focus();next.click();}));
$$('[data-panel]').forEach(button=>button.addEventListener('click',()=>{if(button.dataset.panel==='settings')settingsView();showPanel(button.dataset.panel);}));
$$('[data-settings-view]').forEach(button=>button.addEventListener('click',()=>settingsView(button.dataset.settingsView)));
$$('[data-key]').forEach(button=>button.addEventListener('click',()=>act('remote/key',{key:button.dataset.key})));
$$('[data-home]').forEach(button=>button.addEventListener('click',async()=>{await act('remote/home');category='all';showPanel('sources');$('.app-grid').scrollLeft=0;}));
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
$('#url-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('browser/open-url',{url:$('#web-url').value},'Página abierta'))showPanel('sources');});
$('#load-videos').addEventListener('click',async()=>{
  try {const data=await api('videos');$('#video-list').replaceChildren();
    if(!data.files.length){const item=document.createElement('li');item.textContent='Todavía no hay archivos en Videos.';$('#video-list').append(item);}
    for(const name of data.files){const item=document.createElement('li'),button=document.createElement('button');button.textContent=name;button.addEventListener('click',async()=>{if(await act('videos/play',{name}))showPanel('sources');});item.append(button);$('#video-list').append(item);}
  } catch(error){feedback(error.message,true);}
});
$('#pair-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#pair-form button');button.disabled=true;
  try {const result=await api('session',{token:$('#pair-token').value.trim()});csrf=result.csrf;$('#pair-token').value='';$('#pairing').hidden=true;showPanel('sources');await refresh();}
  catch(error){feedback(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener('keydown',event=>{
  if(!csrf || busy || event.ctrlKey || event.metaKey || event.altKey || ['INPUT','TEXTAREA','BUTTON','A'].includes(event.target.tagName))return;
  const key={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'ok',Escape:'back'}[event.key];
  if(key && state.capabilities?.keys){event.preventDefault();act('remote/key',{key});}
  if(event.key==='Home'){event.preventDefault();act('remote/home');showPanel('sources');}
});
mobile.addEventListener('change',()=>showPanel(panel));
function clock(){const now=new Date();$('#clock').textContent=now.toLocaleTimeString('es-DO',{hour:'2-digit',minute:'2-digit',hour12:false});$('#calendar').textContent=now.toLocaleDateString('es-DO',{weekday:'short',day:'numeric',month:'short'});}
clock();setInterval(clock,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
async function start() {
  showPanel('sources');
  try {const token=fragment.get('pair'); const result=token ? await api('session',{token}) : await api('session');fragment.delete('pair');csrf=result.csrf;$('#pairing').hidden=true;showPanel('sources');await refresh();}
  catch(error){fragment.delete('pair');showPairing();if(kiosk)feedback(error.message,true);}
  setInterval(()=>{if(!document.hidden)refresh();},3000);
}
start();
