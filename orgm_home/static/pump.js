'use strict';
(() => {
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.id = 'pump-open';
  trigger.className = 'pump-open';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3C9 7 5 11 5 15a7 7 0 0 0 14 0c0-4-4-8-7-12Z"/><path d="M8 15a4 4 0 0 0 4 4"/></svg><span>Bomba</span>';
  (document.querySelector('.header-actions') || document.querySelector('.masthead')).append(trigger);

  const dialog = document.createElement('dialog');
  dialog.className = 'pump-dialog';
  dialog.id = 'pump-dialog';
  dialog.setAttribute('aria-labelledby', 'pump-title');
  dialog.innerHTML = `<div class="pump-heading"><h2 id="pump-title">Bomba de agua</h2><button type="button" id="pump-close" aria-label="Cerrar control de bomba"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>
    <p id="pump-state" class="pump-state" role="status" aria-live="polite">Consultando estado…</p>
    <p class="pump-prompt">Elige cuánto tiempo encenderla.</p>
    <div class="pump-times" role="group" aria-label="Encender durante">
      ${[5, 10, 15, 20, 30, 40].map(minutes => `<button type="button" data-pump-minutes="${minutes}" aria-label="Encender bomba durante ${minutes} minutos" disabled><strong>${minutes}</strong><span>min</span></button>`).join('')}
    </div>
    <p class="pump-hint" id="pump-controller">Se apaga automáticamente al terminar.</p>
    <button type="button" id="pump-off" class="pump-off" disabled>Apagar ahora</button>
    <p id="pump-error" class="pump-error" role="alert" hidden></p>
    <button type="button" id="pump-retry" class="pump-retry" hidden>Volver a consultar</button>`;
  document.body.append(dialog);

  const stateLabel = dialog.querySelector('#pump-state');
  const errorLabel = dialog.querySelector('#pump-error');
  const retry = dialog.querySelector('#pump-retry');
  const controls = [...dialog.querySelectorAll('[data-pump-minutes], #pump-off')];
  let inFlight = false;
  let refreshing = false;

  function enabled(value) { controls.forEach(button => { button.disabled = !value; }); }
  function failure(message) {
    enabled(false);
    stateLabel.textContent = 'Estado sin confirmar';
    errorLabel.textContent = message;
    errorLabel.hidden = false;
    retry.hidden = false;
  }
  function render(result) {
    errorLabel.hidden = true;
    retry.hidden = true;
    if (result.state === 'off') stateLabel.textContent = 'Apagada';
    else if (result.remaining_seconds > 0) {
      const seconds = result.remaining_seconds;
      stateLabel.textContent = `Encendida · quedan ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    } else stateLabel.textContent = 'Encendida sin temporizador';
    dialog.querySelector('#pump-controller').textContent = result.fallback
      ? 'Respaldo OrgM activo. Se apaga automáticamente al terminar.'
      : result.controller === 'jarq'
        ? 'Control local de Jarq. Se apaga automáticamente al terminar.'
        : 'Se apaga automáticamente al terminar.';
    enabled(!inFlight);
    dialog.querySelector('#pump-off').disabled = inFlight || result.state === 'off';
  }
  async function request(path, body) {
    const options = {credentials: 'same-origin', headers: {}};
    if (body !== undefined) {
      const session = await fetch('/api/session', {credentials: 'same-origin'});
      if (!session.ok) throw new Error('Vincula este mando antes de controlar la bomba.');
      options.method = 'POST';
      options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': (await session.json()).csrf};
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await fetch(`/api/pump/${path}`, options); }
    catch { throw new Error('No hay conexión. Comprueba la red y vuelve a consultar el estado.'); }
    let result;
    try { result = await response.json(); }
    catch { throw new Error('No se pudo confirmar el estado de la bomba.'); }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'No se pudo completar la acción.');
    return result;
  }
  async function refresh() {
    if (!dialog.open || inFlight || refreshing) return;
    refreshing = true;
    try { render(await request('status')); }
    catch (error) { failure(error.message); }
    finally { refreshing = false; }
  }
  async function action(path, body) {
    if (inFlight) return;
    inFlight = true;
    enabled(false);
    dialog.setAttribute('aria-busy', 'true');
    stateLabel.textContent = path === 'off' ? 'Apagando…' : 'Programando apagado…';
    errorLabel.hidden = true;
    retry.hidden = true;
    try {
      const result = await request(path, body);
      inFlight = false;
      render(result);
    } catch (error) { failure(error.message); }
    finally { inFlight = false; dialog.removeAttribute('aria-busy'); }
  }
  trigger.addEventListener('click', () => { dialog.showModal(); enabled(false); refresh(); });
  dialog.querySelector('#pump-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('keydown', event => event.stopPropagation());
  retry.addEventListener('click', refresh);
  dialog.querySelectorAll('[data-pump-minutes]').forEach(button => button.addEventListener('click', () => action('time', {minutes: Number(button.dataset.pumpMinutes)})));
  dialog.querySelector('#pump-off').addEventListener('click', () => action('off', {}));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden) refresh(); }, 5000);
})();
