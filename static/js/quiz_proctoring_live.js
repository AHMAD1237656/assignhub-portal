/* Exam monitor, Part 1: browser events and camera availability, NO AI claims. */
(() => {
  'use strict';
  const root = document.getElementById('ahp-monitor-root');
  if (!root) return;
  const required = root.dataset.cameraRequired === 'yes';
  const logging = root.dataset.logEvents === 'yes';
  const eventUrl = root.dataset.eventUrl;
  const heartbeatUrl = root.dataset.heartbeatUrl;
  const csrf = document.querySelector('#ahq-csrf-form input[name="csrfmiddlewaretoken"]')?.value;
  const status = document.getElementById('ahp-live-status');
  const video = document.getElementById('ahp-live-video');
  const fullscreenButton = document.getElementById('ahp-fullscreen');
  let stream = null;
  let active = true;
  let hadFullscreen = false;
  let lastEvent = new Map();
  function notify(text, problem=false) { status.textContent = text; status.style.color = problem ? '#a83b35' : '#215a91'; }
  async function post(url, data) {
    if (!active || !csrf) return;
    try {
      const response = await fetch(url, {
        method:'POST', credentials:'same-origin', cache:'no-store', keepalive:true,
        headers:{'X-CSRFToken':csrf,'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},
        body:new URLSearchParams(data)
      });
      if (response.status === 403 || response.status === 404) active = false;
    } catch (_) { notify('Monitoring connection interrupted. Your quiz answers still save independently.', true); }
  }
  function event(kind) {
    if (!logging || !active) return;
    const now = Date.now();
    if (now - (lastEvent.get(kind) || 0) < 10000) return;
    lastEvent.set(kind, now);
    post(eventUrl, {kind});
  }
  function endCamera() {
    if (stream) stream.getTracks().forEach(track=>track.stop());
    stream = null;
  }
  async function startCamera() {
    if (!required) { notify('Browser monitoring active. Camera is not required.'); return; }
    if (!navigator.mediaDevices?.getUserMedia) {
      notify('Camera unavailable; localhost or HTTPS is required.', true); event('MONITOR_ERROR'); return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:360}},audio:false});
      if (video) { video.srcObject = stream; await video.play(); }
      notify('Camera preview active. Browser activity monitor is running.');
      for (const track of stream.getVideoTracks()) track.addEventListener('ended',()=>{
        if (active) { notify('Camera disconnected. Reconnect camera and refresh the page.', true); event('CAMERA_LOST'); }
      });
    } catch (_) { notify('Camera could not be started; tell your teacher if this persists.', true); event('CAMERA_LOST'); }
  }
  document.addEventListener('visibilitychange',()=>{ if (document.hidden) event('TAB_HIDDEN'); });
  window.addEventListener('blur',()=>{ if (!document.hidden) event('WINDOW_BLUR'); });
  document.addEventListener('fullscreenchange',()=>{
    if (document.fullscreenElement) hadFullscreen=true;
    else if (hadFullscreen) event('FULLSCREEN_EXIT');
  });
  fullscreenButton?.addEventListener('click', async ()=>{
    try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); }
    catch (_) { notify('Fullscreen was not enabled. The exam can continue.', true); }
  });
  window.addEventListener('pagehide',()=>{ active=false; endCamera(); });
  setInterval(()=>{ if (active) post(heartbeatUrl, {}); },20000);
  post(heartbeatUrl, {});
  startCamera();
})();
