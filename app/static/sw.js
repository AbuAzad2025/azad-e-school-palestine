var CACHE_NAME = "azad-v1";
var STATIC_ASSETS = [
  "/static/css/brand.css",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/img/azad-mark.svg",
  "/static/manifest.json"
];

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(name) { return name !== CACHE_NAME; }).map(function(name) { return caches.delete(name); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function(event) {
  var url = new URL(event.request.url);
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, clone); });
          return response;
        });
      })
    );
    return;
  }
  event.respondWith(
    fetch(event.request).catch(function() {
      if (event.request.mode === "navigate") {
        return caches.match("/static/offline.html");
      }
      return new Response("", { status: 503, statusText: "Offline" });
    })
  );
});
