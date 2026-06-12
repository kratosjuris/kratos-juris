// Service Worker — Kratos Juris PWA
// Estratégia: network-first (sempre busca dados atualizados do servidor;
// usa cache apenas quando estiver offline).

const CACHE_NAME = 'kratos-juris-v2';

const PRECACHE_URLS = [
  '/static/manifest.json',
  '/static/img/icons/icon-192.png',
  '/static/img/icons/icon-512.png',
  '/offline'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // POST (login, formulários) passa direto, sem interferência
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (event.request.url.includes('/static/')) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(event.request).then((cached) =>
          cached || caches.match('/offline')
        )
      )
  );
});

// =========================================================
// PUSH — recebe a notificação e exibe na tela do celular
// =========================================================
self.addEventListener('push', function (event) {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}

  const title = data.title || 'Kratos Juris';
  const options = {
    body: data.body || '',
    icon: '/static/img/icons/icon-192.png',
    badge: '/static/img/icons/icon-192.png',
    tag: data.tag || 'kratos',
    renotify: true,
    data: { url: data.url || '/dashboard' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Ao tocar na notificação, abre/foca a tela certa
self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/dashboard';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      for (const c of list) {
        if (c.url.includes(url) && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});