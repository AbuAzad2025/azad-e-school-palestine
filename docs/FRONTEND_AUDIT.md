# Frontend audit — asset pipeline, stylesheets, client runtime

Scope: `app/static/js/**`, `app/static/css/**`, `app/templates/**` stylesheet/script
bindings, `app/static/sw.js`. Measured on the tree as of the audit; every
"before" number below is a byte/size count or request count taken from the files
themselves, not an estimate.

## What was wrong

### 1. The CSS build pipeline produced artifacts nothing served

`scripts/build_css.py` bundles each page entry's stylesheet set, inlines
`@import`s, purges unreachable class rules and minifies — and the results are
committed, verified by CI and rebuilt by `deploy/Dockerfile`. No template
referenced them. Every page shipped the raw sources instead:

| page | before | after |
| --- | --- | --- |
| app shell (`base.html`) | 5 `<link>` + 3 inlined `@import`s = **7 blocking files, 224,905 B** | `css/dist/app.min.css` — **1 request, 146,110 B (−35%)** |
| landing | 5 files, 47,735 B | `css/dist/landing.min.css` — 1 request, 30,045 B (−37%) |
| offline fallback | brand.css, 15,065 B | `css/dist/brand.min.css` — 10,136 B (−33%) |
| AI chat | **no page stylesheet at all** | `css/dist/ai-chat.min.css` — 155,469 B |

Requests were also what the service worker had to pay for: it precached
`css/brand.css` and `css/app.css` while the pages asked for neither.

### 2. The AI chat screen never loaded its own stylesheet

`ai-chat.css` (672 lines) defines `.ai-chat-container`, `.ai-chat-sidebar`,
`.ai-chat-content` and the rest of that screen. `templates/ai/chat.html` linked
only the Prism theme, so the page rendered with the app shell and the chat
layout was unstyled. It now overrides the new `app_stylesheet` block with the
`ai-chat` bundle (app shell + `ai-chat.css`), so the page keeps exactly one
bundle. `test_shell_templates_load_the_prebuilt_bundle` guards this.

### 3. The scroll reveal was a stylesheet built at runtime — and it broke hover

`initScrollAnimations()` appended `<style>.azad-in-view{…!important}</style>` on
every page: a parse per load, a CSP nonce lookup, and — because it was
`!important` on `transform` — it pinned every revealed card, cancelling the
`.azad-stat-card:hover` lift that `polish.css` adds. The rule is now static CSS
with a one-class-higher specificity, and the JS only toggles classes.

### 4. The service worker precache list did not match the app

- `/static/img/icons.svg` was missing although `icon()` renders
  `<use href="/static/img/icons.svg#…">` on every page.
- Only 2 of the 8 modules `index.js` imports were precached (`core/theme.js`,
  `components/ui.js`) — the rest (`components/charts.js`, `forms.js`, `tour.js`,
  `core/api.js`, `pages/bulk.js`, `pages/search.js`, dynamic `toast.js`) were
  not, so a first visit that started offline failed on the shell itself.
- `cache.addAll` is atomic: one 404 anywhere aborts the install and leaves the
  app with no worker.
- The `/static/` handler cached every response including 404s, permanently.
- `pages/quiz.js` and `ai-chat.js` were force-precached for every visitor even
  though only their own pages load them.

Now: shell bundle + full entry graph + sprite + manifest + `/offline` are
precached one entry at a time, `/static/` is stale-while-revalidate and only
caches `response.ok`, and page-specific scripts are cached on first use.

### 5. Duplicated reduce-motion reset

`@media (prefers-reduced-motion: reduce)` appeared **three times** in `app.css`
with byte-identical universal `!important` declarations. Value-identical
`!important` copies on the same selector cannot change a computed value, so two
were removed; one copy remains, merged with the `content-visibility` override
that lives in the same media query. Guarded by
`TestMotionPolicy::test_universal_reduced_motion_reset_is_declared_at_most_once`.

### 6. A stale duplicate of the offline page served unrendered Jinja

`app/static/offline.html` was a 2,394-byte copy of `templates/offline.html`
served as a static file, so whoever requested it got `{{ _('…') }}` and
`href="{{ url_for(...) }}"` verbatim — and the stylesheet it asked for was never
fetched because the URL was a Jinja expression. The test that covered it
(`test_offline_page_accessible`) passed, because it matched the Arabic text
sitting *inside* the template expression. The static copy is deleted, the test
now fetches the real `/offline` route and asserts the response contains no
`{{`. The orphan-check helper no longer maps the `/offline` **route** onto a
static filename — that mapping is what hid this file.

### 7. Dead frontend verification

- `tests/test_js_modernization.py` asserted an `app/static/js/modules/` layout
  that no longer exists and skipped itself when it was absent; CI additionally
  deselected it, so the file verified nothing. It now targets `js/core`,
  `js/components` and `js/pages`, is deselected nowhere, and adds a real guard:
  every module `index.js` imports must be in the service-worker precache list.
- `templates/macros/inline_style_cap.html` was a comment-only file that no
  template included.
- `SCROLL_REVEAL_THRESHOLD` / `SCROLL_REVEAL_ROOT_MARGIN` in `app/config/constants.py`
  were referenced nowhere and described a `<style>` that no longer exists.

## Still open (measured, deliberately not changed)

- **`app.css` has 100 byte-identical duplicate rule blocks (12,635 B, ~6% of the
  sheet).** A textual dedupe is *not* cascade-safe: an identical rule can
  legitimately re-assert a value over a conflicting rule that sits between the
  two copies, so removing it is only safe with cascade analysis (or with a
  visual/diff review of the rendered page). Worth a dedicated pass with
  screenshots, not a blind minifier change.
- **`admin.css` (5,350 B, served raw and unpurged) carries rules no template or
  script can match**: `.admin-table` (12 rules, including the entire mobile
  layout), `.badge`/`.badge-*` (6), `.pagination`/`.pagination .current` (2).
  Admin tables in the templates go through the `azad_table` macro, which emits
  `azad-table`. The bundle purge cannot catch these because they live in a
  companion stylesheet, which is never purged.
- **`pages/pure-pages.css` (7,973 B, same situation):** the `.pure-page`,
  `.pure-page__icon`, `.pure-page .pure-btn` and `.pure-page .pure-note` block
  (~60 lines) matches nothing. It was the source of a real visual bug: the
  offline page's markup used `.pure-btn` while every `.pure-btn` rule is scoped
  `.pure-page .pure-btn`, so the retry button could never have been styled by
  it. The offline page's own inline block styles `.btn`.
- **Dead CSS that survives because the purge is conservative by design:**
  `_is_reachable()` keeps any class whose name ends with `-<fragment>` for a
  string literal found in a template, so families like `.pure-page` are retained
  in bundles. Tightening that heuristic trades bytes for regression risk.
- **`app/static/js/video_player.js` (7,775 B)** is loaded by no template
  (documented in `ALLOWED_ORPHANS` in `tests/test_css_architecture.py`).
- **JS is not bundled.** 13 modules / 81,964 B total; the entry graph is 9
  modules / 48,139 B per page (ES modules, so at least it is deferred and
  parallel). `ai-chat.js` (16,423 B) and `pages/quiz.js` (6,720 B) load only on
  their own pages. Bundling or a build step is a larger change than this audit
  should make unilaterally.
- **CDN scripts are render-blocking**: Chart.js on three admin/assessment pages,
  and Prism core + autoloader + marked + DOMPurify + `ai-chat.js` on the chat
  page (all plain `<script src>`, no `defer`). `defer`/`async` (or a local
  bundle) would remove those stalls; the chat page's four libraries must be
  loaded in order, so it needs a small local bundle rather than per-tag `defer`.

## Verification

- `python scripts/build_css.py` — clean; committed `dist/` is byte-identical to
  a fresh build (`test_committed_bundles_match_a_fresh_build`; mutation-checked:
  corrupting a committed bundle makes it fail).
- `pytest tests/test_css_architecture.py tests/test_js_modernization.py
  tests/test_phase8.py tests/test_wcag_aa.py tests/test_offline_client.py
  tests/test_plausible.py tests/test_whatsapp_button.py tests/test_erp_ux_sprint3.py
  tests/test_frontend_critical.py` — **111 passed**.
- `npx vitest run --coverage` — **570 passed**, lines 100% (gate 97),
  functions 98.58% (gate 90).
- `npx biome check app/static/js` — clean. `ruff check` / `ruff format --check`
  / `mypy app config.py run.py` — clean.
- Served pages re-checked through the app test client: the four bundles return
  200, `/` and `/offline` each link exactly one bundle and no source stylesheet,
  `/offline` contains no unrendered Jinja, and `.azad-scroll-hidden.azad-in-view`
  survives the purge without `!important`.
