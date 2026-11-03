/* Camera check and explicit monitoring consent. Not AI inference. */
(() => {
  'use strict';
  const form = document.getElementById('ahp-preflight-form');
  if (!form) return;
  const required = form.dataset.cameraRequired === 'yes';
  const video = document.getElementById('ahp-check-video');
  const button = document.getElementById('ahp-check-camera');
  const status = document.getElementById('ahp-check-status');
  const hidden = document.getElementById('ahp-camera-checked');
  const consent = document.getElementById('ahp-consent');
  const submit = document.getElementById('ahp-start-exam');
  let stream = null;
  let ready = false;
  function update() { submit.disabled = !(consent.checked && (!required || ready)); }
  function stop() { if (stream) { stream.getTracks().forEach(track => track.stop()); stream = null; } }
  consent.addEventListener('change', update);
  button.addEventListener('click', async () => {
    stop(); ready = false; hidden.value = 'no'; update();
    status.textContent = 'Requesting camera access...';
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      status.textContent = 'Camera unavailable: use localhost or HTTPS with a supported browser.';
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({video: {width: {ideal: 640}, height: {ideal: 360}}, audio: false});
      video.srcObject = stream;
      await video.play();
      ready = !!(video.videoWidth && stream.getVideoTracks().some(track => track.readyState === 'live'));
      hidden.value = ready ? 'yes' : 'no';
      status.textContent = ready ? 'Camera preview works. You can start after consenting.' : 'Could not verify a camera frame.';
      for (const track of stream.getVideoTracks()) track.addEventListener('ended', () => {
        ready = false; hidden.value = 'no'; status.textContent = 'Camera disconnected. Recheck the device.'; update();
      });
    } catch (_) { status.textContent = 'Camera permission declined or camera could not start.'; }
    update();
  });
  form.addEventListener('submit', event => {
    if (!consent.checked || (required && !ready)) {
      event.preventDefault(); status.textContent = 'Complete consent and the device check first.';
      return;
    }
    stop();
    submit.disabled = true;
  });
  window.addEventListener('pagehide', stop);
  update();
})();
