var CACHE_NAME = "azad-v5";
// ↑↑↑  BUMP THIS VERSION on every deployment  ↑↑↑
//
// The precache list is the app shell only: the one stylesheet bundle every
// page links, every module index.js pulls in, and the icon sprite (icon()
// renders <use href="/static/img/icons.svg#…">, so it is on every page).
// Page-specific scripts (pages/quiz.js, ai-chat.js) are cached on first visit
// by the /static/ handler below instead of being pushed to every visitor.
var STATIC_ASSETS = [
  "/static/css/dist/app.min.css",
  "/static/css/dist/brand.min.css",
  "/static/js/index.js",
  "/static/js/core/api.js",
  "/static/js/core/theme.js",
  "/static/js/components/charts.js",
  "/static/js/components/forms.js",
  "/static/js/components/toast.js",
  "/static/js/components/tour.js",
  "/static/js/components/ui.js",
  "/static/js/pages/bulk.js",
  "/static/js/pages/search.js",
  "/static/img/azad-mark.svg",
  "/static/img/icons.svg",
  "/static/manifest.json",
  "/offline"
];
var LESSON_CACHE = "azad-lessons-v1";

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      // One entry at a time: `cache.addAll` rejects the whole batch — and so
      // aborts the install, leaving the app with no worker at all — if a
      // single URL 404s.  A missing shell file should cost that file, not
      // offline support.
      return Promise.all(STATIC_ASSETS.map(function(url) {
        return cache.add(url).catch(function() {
          console.warn("[sw] precache skipped", url);
        });
      }));
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(name) { return name !== CACHE_NAME && name !== LESSON_CACHE; }).map(function(name) { return caches.delete(name);  })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function(event) {
  var url = new URL(event.request.url);
  if (url.pathname.startsWith("/static/")) {
    // Stale-while-revalidate: paint instantly from the cache, then refresh it
    // so a deployment reaches returning visitors without waiting for the next
    // CACHE_NAME bump. Only cache successful, same-origin responses — caching
    // a 404 here would keep serving that missing file forever.
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        var network = fetch(event.request).then(function(response) {
          if (response && response.ok && response.type === "basic") {
            var clone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, clone); });
          }
          return response;
        }).catch(function() {
          return cached || new Response("", { status: 503, statusText: "Offline" });
        });
        return cached || network;
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
