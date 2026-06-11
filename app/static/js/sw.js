// Service Worker — Kratos Juris PWA
// Estratégia: network-first (sempre busca dados atualizados do servidor;
// usa cache apenas quando estiver offline).

const CACHE_NAME = 'kratos-juris-v1';

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