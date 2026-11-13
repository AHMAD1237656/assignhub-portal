// Progressive enhancement: the browser polls the unread count every 30 sec.
// All notification data and access decisions remain on Django's server.
(function () {
  'use strict';
  const bell = document.getElementById('ah-notice-bell');
  const badge = document.getElementById('ah-notice-badge');
  if (!bell || !badge) return;
  const url = bell.getAttribute('data-count-url');
  if (!url) return;
  async function update() {
    if (document.hidden) return;
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept':'application/json'}});
      if (!response.ok) return;
      const payload = await response.json();
      const n = Number(payload.unread_count);
      if (!Number.isSafeInteger(n) || n < 0) return;
      badge.textContent = n > 99 ? '99+' : String(n);
      badge.classList.toggle('d-none', n === 0);
      bell.setAttribute('aria-label', `Notifications, ${n} unread`);
    } catch (_ignored) {
      // Offline or server-restarting: keep the existing displayed count.
    }
  }
  window.setInterval(update, 30000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) update(); });
})();
