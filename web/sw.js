// Кэширует оболочку приложения, чтобы Искра открывалась без интернета.
const CACHE = 'iskra-v1';
const SHELL = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './brain.js',
  './store.js',
  './claude.js',
  './manifest.webmanifest',
  './icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // Запросы к API и поиску всегда идут в сеть.
  if (url.origin !== self.location.origin && !url.hostname.endsWith('jsdelivr.net')) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((res) => {
          if (res.ok) caches.open(CACHE).then((c) => c.put(request, res.clone()));
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((list) => {
      if (list[0]) return list[0].focus();
      return self.clients.openWindow('./index.html');
    })
  );
});
