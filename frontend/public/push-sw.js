/* Service worker do canal "Navegador" (Web Push). Serve apenas para receber avisos e abrir o sistema ao clicar. */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'Plataforma de Gestão de TI';
  const url = typeof data.url === 'string' && data.url.startsWith('/') ? data.url : '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      // Com o sistema à vista, o sino já avisou: evita pop-up duplicado.
      if (windows.some((w) => w.visibilityState === 'visible')) return undefined;
      return self.registration.showNotification(title, {
        body: data.body || '',
        icon: '/favicon.ico',
        data: { url },
        tag: url, // várias respostas no mesmo chamado viram um aviso só
        renotify: true,
        requireInteraction: data.priority === 'critical'
      });
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (windows) => {
      for (const w of windows) {
        try {
          await w.focus();
          if ('navigate' in w) await w.navigate(target);
          return undefined;
        } catch (_) {
          /* tenta a próxima janela ou abre uma nova */
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
