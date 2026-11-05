import RFB from '/vnc-client/core/rfb.js';

export function connectScreen(target, connected, disconnected) {
  const url = new URL('/api/remote/live', location.href);
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const rfb = new RFB(target, url.href);
  rfb.viewOnly = true;
  rfb.scaleViewport = true;
  rfb.resizeSession = false;
  rfb.clipViewport = false;
  rfb.qualityLevel = 5;
  rfb.compressionLevel = 2;
  rfb.addEventListener('connect', connected);
  rfb.addEventListener('disconnect', disconnected);
  return rfb;
}
