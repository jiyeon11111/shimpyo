/* 화면 파일만 캐시한다. API 응답은 캐시하지 않는다 (판정은 항상 서버 최신값). */
const CACHE = "shimpyo-v2";
const FILES = ["/", "/index.html", "/style.css", "/app.js", "/logo.js", "/manifest.webmanifest", "/icons/icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES))));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith("/api/") || e.request.method !== "GET") return;
  e.respondWith(fetch(e.request).then(r => { caches.open(CACHE).then(c => c.put(e.request, r.clone())); return r; }).catch(() => caches.match(e.request)));
});
