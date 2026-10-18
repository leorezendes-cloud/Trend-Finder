/* Network-only live pages. Only these public offline assets enter Cache Storage. */
const CACHE_PREFIX = 'trendfindah-offline-';
const CACHE_NAME = CACHE_PREFIX + '__ASSET_VERSION__';
const OFFLINE = '/static/pwa/offline.html';
const ASSETS = [OFFLINE, '/static/pwa/icon-192.svg', '/static/pwa/icon-512.svg'];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
    event.waitUntil(caches.keys().then(names => Promise.all(
        names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
            .map(name => caches.delete(name))
    )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);
    // POST forms, scores, APIs, reset tokens and private data always use the browser network path.
    if (request.method !== 'GET' || url.origin !== self.location.origin) return;
    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(async () => {
            const cache = await caches.open(CACHE_NAME);
            return await cache.match(OFFLINE) || Response.error();
        }));
    } else if (ASSETS.includes(url.pathname) && !url.search) {
        event.respondWith(caches.open(CACHE_NAME).then(async cache => await cache.match(request) || fetch(request)));
    }
});
