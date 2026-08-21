var CACHE_NAME = "azad-v3";
var STATIC_ASSETS = [
  "/static/css/brand.css",
  "/static/css/app.css",
  "/static/js/index.js",
  "/static/js/modules/api.js",
  "/static/js/modules/theme.js",
  "/static/js/modules/ui.js",
  "/static/js/modules/toast.js",
  "/static/img/azad-mark.svg",
  "/static/manifest.json",
  "/offline"
];
var LESSON_CACHE = "azad-lessons-v1";

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
        names.filter(function(name) { return name !== CACHE_NAME && name !== LESSON_CACHE; }).map(function(name) { return caches.delete(name); })
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
  // Network-first for lesson content with offline fallback
  if (url.pathname.startsWith("/content/lessons/") || url.pathname.startsWith("/content/units/")) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        var clone = response.clone();
        caches.open(LESSON_CACHE).then(function(cache) { cache.put(event.request, clone); });
        return response;
      }).catch(function() { return caches.match(event.request); })
    );
    return;
  }
  event.respondWith(
    fetch(event.request).catch(function() {
      if (event.request.mode === "navigate") {
        return caches.match("/offline");
      }
      return new Response("", { status: 503, statusText: "Offline" });
    })
  );
});
