'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let csrf = null;
let state = {session:false,capabilities:{}};
let busy = false;
let panel = 'sources';
let feedbackTimer;
const mobile = matchMedia('(max-width: 720px)');
const labels = Object.fromEntries($$('[data-app]').map(button => [button.dataset.app, button.querySelector('.app-name').textContent]));
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
  for (const id of ['sources','remote','typing']) {
    const visible = paired && (kiosk ? id==='sources' : mobile.matches ? id===next : next==='typing' ? id==='typing' : id!=='typing');
    $(`#${id}`).hidden=!visible;
  }
  $$('[data-panel]').forEach(button => {if (button.dataset.panel===next) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');});
}
function showPairing() { $('#pairing').hidden=false; showPanel(panel); $('#connection-label').textContent='Sin vincular'; $('#connection').className='connection'; }
function render() {
  const online=Boolean(state.session);
  $('#connection-label').textContent=online ? 'Sala conectada' : 'Sala sin conexión';
  $('#connection').className=`connection ${online ? 'online' : 'error'}`;
  const active=labels[state.app] || 'Selecciona una aplicación';
  $('#remote-title').textContent=state.app && state.app!=='home' ? active : 'Mando';
  $('#current-label').textContent=online ? active : 'La sala no está disponible';
  $('#current-detail').textContent=online ? (state.title || 'Lista para empezar') : (state.warning || 'Comprueba que el equipo esté encendido');
  $('#volume-value').textContent=state.volume===null || state.volume===undefined ? '—' : `${state.volume}%`;
  $('#mute').setAttribute('aria-pressed',String(Boolean(state.muted)));
  $('#mute').setAttribute('aria-label',state.muted ? 'Activar audio' : 'Silenciar audio');
  const brightness=$('#brightness');
  brightness.disabled=!online || busy || state.brightness===null || state.brightness===undefined;
  $$('[data-brightness]').forEach(button=>button.disabled=brightness.disabled);
  $('#rotate-screen').disabled=!online || busy;
  if(document.activeElement!==brightness) {
    if(state.brightness!==null && state.brightness!==undefined) brightness.value=state.brightness;
    $('#brightness-value').textContent=state.brightness===null || state.brightness===undefined ? 'No disponible' : `${state.brightness}%`;
  }
  $$('[data-app]').forEach(button=>{
    button.disabled=!online || busy;
    button.classList.toggle('is-active',button.dataset.app===state.app);
    button.classList.toggle('is-open',(state.open || []).includes(button.dataset.app));
    button.setAttribute('aria-pressed',String(button.dataset.app===state.app));
    button.setAttribute('aria-label',`${labels[button.dataset.app]}${button.dataset.app===state.app ? ', en pantalla' : (state.open || []).includes(button.dataset.app) ? ', abierta' : ''}`);
  });
  $$('[data-key]').forEach(button=>{const key=button.dataset.key; const capability=key==='mute' ? state.volume!==null : key==='play' ? state.capabilities?.play : state.capabilities?.keys;button.disabled=!online || busy || !capability;});
  $$('[data-home],[data-volume],#url-form button,#load-videos').forEach(button=>button.disabled=!online || busy);
  $('#text-form button[type=submit]').disabled=!online || busy || !state.capabilities?.text;
  $('#close-app').hidden=!state.capabilities?.close;
  $('#close-app').disabled=busy;
  $('#control-note').textContent=state.app==='home' ? 'Abre una aplicación para usar el mando.' : state.app==='spotify' ? 'Play y pausa controlan Spotify. La navegación puede variar.' : ['netflix','max','crunchyroll','browser'].includes(state.app) ? 'Las teclas dependen de la página. Usa Teclado para búsquedas.' : 'Los controles dependen de cada aplicación.';
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
$$('[data-app]').forEach(button=>button.addEventListener('click',async()=>{
  button.setAttribute('aria-busy','true');
  const result=await act(`apps/${button.dataset.app}/activate`,{},`Abriendo ${labels[button.dataset.app]}`);
  button.removeAttribute('aria-busy');
  if(result && !kiosk) {
    if(button.dataset.app==='videos'){showPanel('typing');$('#load-videos').click();}
    else showPanel('remote');
  }
}));
$$('[data-panel]').forEach(button=>button.addEventListener('click',()=>showPanel(button.dataset.panel)));
$$('[data-key]').forEach(button=>button.addEventListener('click',()=>act('remote/key',{key:button.dataset.key})));
$$('[data-home]').forEach(button=>button.addEventListener('click',async()=>{await act('remote/home');showPanel('sources');}));
$$('[data-volume]').forEach(button=>button.addEventListener('click',()=>act('audio/volume',{delta:Number(button.dataset.volume)})));
$('#close-app').addEventListener('click',()=>act('remote/close',{},'Aplicación cerrada'));
$('#brightness').addEventListener('input',event=>$('#brightness-value').textContent=`${event.target.value}%`);
$('#brightness').addEventListener('change',event=>act('display/brightness',{value:Number(event.target.value)}));
$$('[data-brightness]').forEach(button=>button.addEventListener('click',()=>act('display/brightness',{value:Number(button.dataset.brightness)})));
$('#rotate-screen').addEventListener('click',()=>act('display/rotate',{},'Pantalla táctil girada'));
$('#text-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('remote/text',{text:$('#remote-text').value},'Texto enviado'))$('#remote-text').value='';});
$('#url-form').addEventListener('submit',async event=>{event.preventDefault();if(await act('browser/open-url',{url:$('#web-url').value},'Página abierta'))showPanel('remote');});
$('#load-videos').addEventListener('click',async()=>{
  try {const data=await api('videos');$('#video-list').replaceChildren();
    if(!data.files.length){const item=document.createElement('li');item.textContent='Todavía no hay archivos en Videos.';$('#video-list').append(item);}
    for(const name of data.files){const item=document.createElement('li'),button=document.createElement('button');button.textContent=name;button.addEventListener('click',async()=>{if(await act('videos/play',{name}))showPanel('remote');});item.append(button);$('#video-list').append(item);}
  } catch(error){feedback(error.message,true);}
});
$('#pair-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#pair-form button');button.disabled=true;
  try {const result=await api('session',{token:$('#pair-token').value.trim()});csrf=result.csrf;$('#pair-token').value='';$('#pairing').hidden=true;showPanel('sources');await refresh();}
  catch(error){feedback(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener('keydown',event=>{
  if(!csrf || busy || event.ctrlKey || event.metaKey || event.altKey || ['INPUT','TEXTAREA','BUTTON','A'].includes(event.target.tagName))return;
  const key={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'ok',Escape:'back',' ':'play'}[event.key];
  if(key && state.capabilities?.keys){event.preventDefault();act('remote/key',{key});}
  if(event.key==='Home'){event.preventDefault();act('remote/home');showPanel('sources');}
});
mobile.addEventListener('change',()=>showPanel(panel));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
async function start() {
  showPanel('sources');
  try {const token=fragment.get('pair'); const result=token ? await api('session',{token}) : await api('session');fragment.delete('pair');csrf=result.csrf;$('#pairing').hidden=true;showPanel('sources');await refresh();}
  catch(error){fragment.delete('pair');showPairing();if(kiosk)feedback(error.message,true);}
  setInterval(()=>{if(!document.hidden)refresh();},3000);
}
start();
