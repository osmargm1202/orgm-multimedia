function(options) {
  if(!document.hasFocus() || document.visibilityState!=='visible')return {ok:false,error:'La página dejó de estar enfocada.'};
  const editable=el=>el && !el.disabled && !el.readOnly && (el.isContentEditable || el.tagName==='TEXTAREA' || (el.tagName==='INPUT' && ['text','search','email','url','tel','password','number'].includes(el.type)));
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>3&&r.height>3&&s.visibility!=='hidden'&&s.display!=='none'&&!el.closest('[inert],[aria-hidden="true"]');};
  const symbol=Symbol.for('orgm.remote-input');
  const state=window[symbol]||(window[symbol]={ids:new WeakMap(),nodes:new Map()});
  for(const [id,node] of state.nodes)if(!node.isConnected)state.nodes.delete(id);
  const active=()=>{let el=document.activeElement;while(el?.shadowRoot?.activeElement)el=el.shadowRoot.activeElement;return el;};
  const identify=el=>{
    if(!state.ids.has(el)){const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('');state.ids.set(el,id);state.nodes.set(id,el);}
    return state.ids.get(el);
  };
  if(options.action==='edit') {
    const el=state.nodes.get(options.id);
    if(!el || active()!==el || !editable(el) || !visible(el))return {ok:false,error:'El campo cambió. Vuelve a seleccionarlo.'};
    return {ok:true};
  }
  const nodes=[];
  const collect=root=>{for(const el of root.querySelectorAll('*')){if(nodes.length>=100)break;if(editable(el)&&visible(el))nodes.push(el);if(el.shadowRoot)collect(el.shadowRoot);}};
  collect(document);
  const describe=el=>{const r=el.getBoundingClientRect();return {id:identify(el),x:r.x,y:r.y,width:r.width,height:r.height,type:el.type||'text'};};
  const focused=active();
  return {ok:true,viewport:{width:innerWidth,height:innerHeight},fields:nodes.map(describe),focused:editable(focused)&&visible(focused)?describe(focused):null};
}
