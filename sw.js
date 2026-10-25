// Keeps the app and its photos available offline. Bump VERSION on each release so phones pick up the new page.
const VERSION = "v8";
const SHELL = ["./", "index.html", "firebase-config.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open("shell-" + VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith("shell-") && k !== "shell-" + VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.endsWith("/data/seed.json")) return;
  // Photos never change: cache first. The page itself: network first, cache when offline.
  if (url.pathname.includes("/photos/")) {
    e.respondWith(caches.open("photos").then(c => c.match(e.request).then(r => r || fetch(e.request).then(res => { if (res.ok) c.put(e.request, res.clone()); return res; }))));
    return;
  }
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) caches.open("shell-" + VERSION).then(c => c.put(e.request, res.clone()));
    return res;
  }).catch(() => caches.match(e.request)));
});
