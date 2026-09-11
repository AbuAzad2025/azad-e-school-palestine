"""Sweep static inline styles in templates → utility classes (merge-aware).

Usage:
    python scripts/sweep_inline_styles.py           # apply mapped rewrites
    python scripts/sweep_inline_styles.py --report  # only report leftovers

Idempotent: mapped styles are removed, their utility classes merged into
the tag's existing class attribute. Dynamic styles (containing {{ or {%)
are never touched here — they are handled per-template.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

# normalized inline CSS -> utility classes
MAP: dict[str, list[str]] = {
    "display:inline": ["u-inline"],
    "display:none": ["u-none"],
    "width:100%": ["u-w-full"],
    "text-align:center": ["u-text-center"],
    "font-weight:600": ["u-bold"],
    "color:var(--muted)": ["u-muted"],
    "margin:0": ["u-m-0"],
    "margin:2px": ["u-m-2px"],
    "margin-top:0": ["u-mt-0"],
    "margin-top:.25rem": ["u-mt-0-25"],
    "margin-top:0.5rem": ["u-mt-0-5"],
    "margin-top:.5rem": ["u-mt-0-5"],
    "margin-top:1rem": ["u-mt-1"],
    "margin-top:1.5rem": ["u-mt-1-5"],
    "margin-top:2rem": ["u-mt-2"],
    "margin-top:3rem": ["u-mt-3"],
    "margin-top:4rem": ["u-mt-4"],
    "margin-bottom:1rem": ["u-mb-1"],
    "margin-bottom:1.5rem": ["u-mb-1-5"],
    "margin-bottom:2rem": ["u-mb-2"],
    "margin:0.5rem 0": ["u-my-0-5"],
    "margin:2rem 0": ["u-my-2"],
    "margin:2rem auto": ["u-my-2", "u-mx-auto"],
    "margin:0 0 var(--sp-4)": ["u-mb-0sp4"],
    "margin-bottom:var(--sp-4)": ["u-mb-sp4"],
    "margin-bottom:var(--sp-3)": ["u-mb-sp3"],
    "margin-bottom:0": ["u-mb-0"],
    "font-size:.75rem": ["u-text-xs"],
    "font-size:.7rem": ["u-text-xs"],
    "font-size:0.75rem": ["u-text-xs"],
    "font-size:0.85rem": ["u-text-sm"],
    "font-size:.85rem": ["u-text-sm"],
    "max-width:600px": ["u-maxw-600"],
    "max-width:640px;margin:2rem auto": ["u-center-box"],
    "overflow-x:auto": ["u-overflow-x-auto"],
    "flex:1;min-width:200px": ["u-flex-1-min"],
    "display:flex;gap:1rem;flex-wrap:wrap": ["u-flex-wrap-gap"],
    "display:flex;gap:var(--sp-2);align-items:center": ["u-flex-between"],
    "height:300px": ["u-h-300"],
    "grid-template-columns:repeat(auto-fill,minmax(200px,1fr))": ["u-grid-cards"],
    "grid-template-columns:repeat(auto-fit,minmax(200px,1fr))": ["u-grid-cards--fit"],
    "white-space:pre-wrap": ["u-pre-wrap"],
    # progress track (static outer div) -> .meter component
    "width:100px;height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden": [
        "meter"
    ],
    "width:100px;height:8px;background:var(--surface-hover);border-radius:4px;overflow:hidden": [
        "meter"
    ],
    # navy filter/submit field used on list pages
    "flex:1;padding:.3rem;font-size:.9rem;border:1px solid var(--azad-navy);background:var(--azad-navy);color:#fff": [
        "u-field--navy"
    ],
    # ── Extension 2: composable ──
    "flex:1": ["u-flex-1"],
    "flex:0": ["u-flex-none"],
    "flex-shrink:0": ["u-shrink-0"],
    "align-self:end": ["u-self-end"],
    "min-width:140px": ["u-minw-140"],
    "min-width:160px": ["u-minw-160"],
    "width:auto": ["u-w-auto"],
    "width:auto;min-width:140px": ["u-w-auto", "u-minw-140"],
    "width:auto;min-width:180px": ["u-w-auto", "u-minw-180"],
    "width:240px": ["u-w-240"],
    "max-width:120px": ["u-maxw-120"],
    "max-width:110px": ["u-maxw-110"],
    "max-width:100px": ["u-maxw-100"],
    "max-width:500px": ["u-maxw-500"],
    "max-width:800px;margin:0 auto": ["u-center-800-nm"],
    "max-width:700px;margin:0 auto": ["u-center-700-nm"],
    "max-width:760px;margin:2rem auto": ["u-center-760"],
    "max-width:800px;margin:2rem auto": ["u-center-800"],
    "max-width:960px;margin:2rem auto": ["u-center-960"],
    "max-width:700px;margin:2rem auto;padding:2rem": ["u-center-700-p2"],
    "color:var(--color-danger)": ["u-text-danger"],
    "color:var(--azad-danger,#dc3545)": ["u-text-danger-fb"],
    "color:var(--azad-red)": ["u-text-red"],
    "color:var(--azad-green)": ["u-text-green"],
    "color:var(--azad-amber)": ["u-text-amber"],
    "color:var(--azad-muted)": ["u-text-azad-muted"],
    "color:var(--azad-muted);margin-bottom:1.5rem": ["u-text-azad-muted", "u-mb-1-5"],
    "color:var(--muted);margin-bottom:var(--sp-4)": ["u-muted", "u-mb-sp4"],
    "color:var(--muted);margin:0": ["u-muted", "u-m-0"],
    "color:var(--muted);margin-bottom:var(--sp-6)": ["u-muted", "u-mb-sp6"],
    "color:var(--muted);font-size:var(--text-sm)": ["u-muted", "u-text-sm-t"],
    "color:var(--azad-red);font-size:var(--text-sm)": ["u-text-red", "u-text-sm-t"],
    "font-size:var(--text-sm)": ["u-text-sm-t"],
    "font-size:var(--text-lg)": ["u-text-lg-t"],
    "font-size:1.25rem": ["u-text-1-25"],
    "font-size:0.875rem": ["u-text-sm"],
    "font-size:0.8em;color:var(--text-muted);margin-bottom:0.5rem": ["u-text-08em", "u-muted", "u-mb-0-5"],
    "font-size:0.8em;color:var(--text-muted);margin-top:0.5rem": ["u-text-08em", "u-muted", "u-mt-0-5"],
    "font-size:0.9em;color:var(--text-muted);margin-bottom:0.5rem": ["u-text-09em", "u-muted", "u-mb-0-5"],
    "font-size:.85rem;color:var(--muted);margin-top:.4rem": ["u-text-sm", "u-muted", "u-mt-0-4"],
    "margin-top:.3rem": ["u-mt-0-3"],
    "margin-top:.6rem;padding:.8rem": ["u-mt-0-6", "u-p-08"],
    "margin-top:.5rem;display:block;opacity:.8": ["u-mt-0-5", "u-block", "u-op-80"],
    "margin-top:0.75rem;font-size:0.8rem": ["u-mt-0-75", "u-text-08rem"],
    "margin-top:1rem;display:inline": ["u-mt-1", "u-inline"],
    "margin-top:3rem;text-align:center": ["u-mt-3", "u-text-center"],
    "margin-top:2rem;font-size:.8rem;color:var(--text-muted)": ["u-offline-note"],
    "margin:.5rem 0": ["u-my-0-5"],
    "text-align:center;padding:1.5rem": ["u-text-center", "u-p-15"],
    "text-align:center; padding:1.5rem;": ["u-text-center", "u-p-15"],
    "text-align:center; padding:1.5rem; opacity:0.6;": ["u-text-center", "u-p-15", "u-op-60"],
    "text-align:center;padding:3rem": ["u-text-center", "u-p-3r"],
    "text-align:center;margin-top:1rem": ["u-text-center", "u-mt-1"],
    "text-align:center;margin-top:var(--sp-4);color:var(--muted);font-size:var(--text-sm)": [
        "u-text-center",
        "u-mt-sp4",
        "u-muted",
        "u-text-sm-t",
    ],
    "text-align:center;font-weight:700;letter-spacing:.2em": ["u-code-display"],
    "font-size:2rem; font-weight:700; letter-spacing:0.3em; color:var(--azad-navy); font-family:monospace;": [
        "u-heading-navy"
    ],
    "font-size:2rem;font-weight:700;letter-spacing:0.3em;color:var(--azad-n": ["u-heading-navy"],
    "font-weight:700": ["u-bolder"],
    "font-weight:700;color:var(--azad-blue)": ["u-bolder", "u-text-blue"],
    "grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))": ["u-grid-cards--fit"],
    "grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))": ["u-grid-cards"],
    "grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));": ["u-grid-cards--fit"],
    "grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));": ["u-grid-cards"],
    "grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));margin-bottom:2rem": ["u-grid-cards--fit", "u-mb-2"],
    "grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-bottom:var(--sp-6)": [
        "u-grid-cards--fit",
        "u-mb-sp6",
    ],
    "grid-template-columns:repeat(auto-fill,minmax(200px,1fr));margin-bottom:var(--sp-6)": [
        "u-grid-cards",
        "u-mb-sp6",
    ],
    "grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));": ["u-grid-cards-180"],
    "grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));": ["u-grid-cards-300"],
    "grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));": ["u-grid-fill-300"],
    "grid-template-columns:repeat(auto-fit, minmax(200px, 1fr))": ["u-grid-cards--fit"],
    "grid-template-columns:repeat(auto-fit, minmax(300px, 1fr))": ["u-grid-cards-300"],
    "display:grid;gap:var(--sp-2)": ["u-grid-sp2"],
    "display:grid;gap:var(--sp-4)": ["u-grid-sp4"],
    "display:grid;gap:var(--sp-4);grid-template-columns:repeat(auto-fill,minmax(280px,1fr))": ["u-cards-280"],
    "display:grid;gap:var(--sp-4);grid-template-columns:repeat(auto-fit,minmax(400px,1fr))": ["u-grid-400-2r"],
    "display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:2rem;margin-top:2rem": [
        "u-grid-400-2r"
    ],
    "display:grid;grid-template-columns:1fr 1fr;gap:1rem": ["u-grid-2col"],
    "display:grid;grid-template-columns:1fr 1fr;gap:.5rem": ["u-grid-2col-sm"],
    "display:grid;gap:var(--sp-4);grid-template-columns:repeat(auto-fill,mi": ["u-grid-cards"],
    "display:grid;gap:var(--sp-4);grid-template-columns:repeat(auto-fit,min": ["u-grid-cards--fit"],
    "display:flex;gap:.5rem;cursor:pointer": ["u-flex", "u-gap-0-5", "u-click"],
    "display:flex;gap:.5rem;margin-bottom:.5rem": ["u-flex", "u-gap-0-5", "u-mb-0-5"],
    "display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.6rem": ["u-flex", "u-gap-0-5", "u-wrap", "u-mt-0-6"],
    "display:flex;gap:.75rem;flex-wrap:wrap": ["u-wrap-gap-075"],
    "display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1rem": ["u-wrap-gap-075", "u-mb-1"],
    "display:flex;gap: 0.75rem;flex-wrap: wrap;": ["u-wrap-gap-075"],
    "gap: 0.75rem; flex-wrap: wrap;": ["u-wrap-gap-075"],
    "gap:.5rem;margin-bottom:1rem": ["u-gap-0-5", "u-mb-1"],
    "display:flex;gap:1rem;align-items:center;flex-wrap:wrap": ["u-flex", "u-gap-1", "u-items-center", "u-wrap"],
    "display:flex;gap:1rem;align-items:start;padding:.75rem;border-bottom:1px solid var(--azad-border);cursor:pointer": [
        "u-row-item"
    ],
    "display:flex;gap:2rem;justify-content:center;flex-wrap:wrap;margin-top:1.5rem": ["u-center-2r"],
    "display:flex;justify-content:center;gap:var(--sp-2);margin-bottom:var(--sp-6)": ["u-center-row"],
    "display:flex;justify-content:space-between;padding:var(--sp-2) 0;border-bottom:1px solid var(--border, #e2e8f0)": [
        "u-list-row"
    ],
    "display:flex;justify-content:space-between;flex-wrap:wrap;gap:var(--sp-2)": ["u-between-wrap"],
    "display:flex;justify-content:space-between;align-items:start;gap:1rem": ["u-between-start"],
    "display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--sp-2)": [
        "u-between-wrap-sp2"
    ],
    "display:flex;justify-content:space-between;margin-b": ["u-between-mb-sp4"],
    "display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--sp-4)": [
        "u-between-mb-sp4"
    ],
    "display:flex;align-items:center;gap:.5rem": ["u-flex", "u-items-center", "u-gap-0-5"],
    "display:flex;align-items:center;gap:.5rem;background:#25D366;border-color:#25D366;color:#fff": [
        "u-wa-btn"
    ],
    "display:flex;align-items:center;gap:var(--sp-4);margin:var(--sp-4) 0": ["u-tour-row"],
    "display:flex;align-items:end;padding-bottom:.5rem": ["u-row-end"],
    "display:flex;gap:1rem;align-items:end": ["u-flex", "u-gap-1", "u-flex-end"],
    "display:flex;gap:var(--sp-4);flex-wrap:wrap;margin-bottom:var(--sp-6)": ["u-panel-gapsp4"],
    "display:flex;gap:var(--sp-3);margin-top:var(--sp-2);color:var(--muted)": [
        "u-flex-sp3",
        "u-mt-sp2",
        "u-muted",
    ],
    "display:flex;gap:var(--sp-3);margin-bottom:var(--sp-3);flex-wrap:wrap;align-items:end;padding:var(--sp-3);background:var(--azad-slate);border-radius:var(--radius-lg)": [
        "u-slate-row"
    ],
    "display:inline;margin-right:.5rem": ["u-inline", "u-me-0-5"],
    "display:inline-flex;gap:.5rem": ["u-inline-flex-gap-05"],
    "flex-direction:row": ["u-flex-row"],
    "background:var(--surface-2)": ["u-bg-surface-2"],
    "background:var(--azad-green)": ["u-bg-green"],
    "background:var(--azad-green);color:#fff": ["u-bg-green-solid"],
    "background:var(--azad-gold);color:#fff": ["u-bg-gold-solid"],
    "background:var(--azad-amber)": ["u-bg-amber"],
    "background:var(--azad-gray-400)": ["u-bg-gray-400"],
    "background:var(--azad-gray-500)": ["u-bg-gray-500"],
    "background:var(--azad-indigo)": ["u-bg-indigo"],
    "background:#fff;color:var(--azad-navy)": ["u-bg-navy-inverse"],
    "background:var(--azad-green);color:#fff;": ["u-bg-green-solid"],
    "font-size:3rem;margin-bottom:0.5rem;color:var(--azad-gray-400)": ["u-display-3", "u-mb-0-5", "u-text-gray-400"],
    "font-size:3rem;margin-bottom:0.5rem;color:var(--azad-amber)": ["u-display-3", "u-mb-0-5", "u-text-amber"],
    "font-size:3rem; margin-bottom:0.5rem; color:var(--azad-gray-400);": ["u-display-3", "u-mb-0-5", "u-text-gray-400"],
    "font-size:3rem; margin-bottom:0.5rem; color:var(--azad-amber);": ["u-display-3", "u-mb-0-5", "u-text-amber"],
    "margin-top:1.5rem;border:1px solid var(--azad-navy);border-radius:var(--radius);background:var(--azad-navy);color:#fff;padding:1rem": [
        "u-callout-navy-solid"
    ],
    "width:100%;padding:.5rem;font-size:.9rem;margin-bottom:.5rem;border:1px solid var(--azad-navy);background:var(--azad-navy);color:#fff": [
        "u-filter-navy"
    ],
    "margin-bottom:var(--sp-4);padding:var(--sp-4);background:var(--azad-slate);border-radius:var(--radius-lg)": [
        "u-slate-box"
    ],
    "padding:var(--sp-4);background:var(--azad-slate);border-radius:var(--r": ["u-slate-box"],
    "padding:var(--sp-4);background:var(--azad-slate);border-radius:var(--radius-lg)": ["u-slate-box"],
    "margin:0 0 var(--sp-3)": ["u-mb-0sp3"],
    "margin:var(--sp-6) 0 var(--sp-3)": ["u-m-sp6-0-sp3"],
    "margin-bottom:var(--sp-3);display:flex;gap:var(--sp-2)": ["u-mb-sp3", "u-flex", "u-gap-sp2"],
    "margin-top:var(--sp-3);padding-top:var(--sp-3);border-top:1px solid var(--border, #e2e8f0)": ["u-divided"],
    "border-top:1px solid var(--azad-border);padding:1rem;display:flex;gap:": ["u-panel-foot"],
    "border-top:1px solid var(--azad-border);padding:1rem;display:flex;gap:.5rem;justify-content:flex-end": [
        "u-panel-foot"
    ],
    "border-bottom:1px solid var(--azad-border);padding:.75rem 0": ["u-divided-row"],
    "text-align:center; padding:2rem; background:var(--bg-secondary); border-radius:var(--radius-lg); margin:1rem 0;": [
        "u-empty-box"
    ],
    "text-align:center;padding:2rem;background:var(--bg-secondary);border-r": ["u-empty-box"],
    "width:120px;height:8px;background:var(--bg-secondary);border-radius:4p": ["meter", "meter--w120"],
    "width:120px;height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden": [
        "meter",
        "meter--w120",
    ],
    "flex:1;min-width:80px": ["u-flex-1-80"],
    "flex:1;min-width:120px": ["u-flex-1-120"],
    "flex:1;min-width:160px": ["u-flex-1-160"],
    "flex:2;min-width:140px": ["u-flex-2-140"],
    "flex:2;min-width:200px": ["u-flex-2-200"],
    "flex:3;min-width:160px": ["u-flex-3-160"],
    "margin-top:1.5rem;border:1px solid var(--azad-navy);border-radius:var(--radius);background:var(--azad-navy);color:#fff;padding:1rem;": [
        "u-callout-navy-solid"
    ],
    "color:var(--muted);text-align:center;max-width:700px;margin:0 auto": ["u-center-700-nm", "u-muted", "u-text-center"],
    "width:100%;margin-top:1rem": ["u-mt-1-w100"],
    "margin-bottom:1.5rem;opacity:0.9": ["u-mb-15-op90"],
    "padding:var(--sp-4);background:var(--azad-slate);border-radius:var(--radius-lg);margin-bottom:var(--sp-4)": [
        "u-slate-box-mb"
    ],
}


def norm(css: str) -> str:
    css = css.strip().rstrip(";").strip()
    css = re.sub(r"\s*:\s*", ":", css)
    css = re.sub(r";\s*", ";", css)
    css = re.sub(r"\s+", " ", css)
    return css


# canonicalize keys at import time so spacing/semicolon variants always match
for _k, _v in list(MAP.items()):
    _nk = norm(_k)
    if _nk != _k:
        MAP[_nk] = _v
        del MAP[_k]

TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
STYLE_RE = re.compile(r'\sstyle="([^"]*)"')


def merge_classes(tag: str, classes: list[str]) -> str:
    m = re.search(r'class="([^"]*)"', tag)
    if m:
        existing = m.group(1).split()
        merged = existing + [c for c in classes if c not in existing]
        return tag[: m.start()] + 'class="' + " ".join(merged) + '"' + tag[m.end() :]
    m2 = re.match(r"<([a-zA-Z][a-zA-Z0-9]*)", tag)
    assert m2
    return tag[: m2.end()] + ' class="' + " ".join(classes) + '"' + tag[m2.end() :]


def sweep_file(path: Path, apply: bool) -> tuple[int, list[str]]:
    src = path.read_text(encoding="utf-8")
    converted = 0
    unmapped: list[str] = []

    def process_tag(tag: str) -> str:
        nonlocal converted
        m = STYLE_RE.search(tag)
        if not m:
            return tag
        style_val = m.group(1)
        if "{{" in style_val or "{%" in style_val:
            unmapped.append(f"dynamic: {style_val[:70]}")
            return tag
        n = norm(style_val)
        classes = MAP.get(n)
        if classes is None:
            unmapped.append(n[:70])
            return tag
        converted += 1
        tag_wo = tag[: m.start()] + tag[m.end() :]
        return merge_classes(tag_wo, classes)

    out = TAG_RE.sub(lambda t: process_tag(t.group(0)), src)
    if apply and out != src:
        path.write_text(out, encoding="utf-8")
    return converted, unmapped


def main() -> int:
    apply = "--report" not in sys.argv
    total = 0
    leftovers: list[str] = []
    for p in sorted(TEMPLATES.rglob("*.html")):
        c, unmapped = sweep_file(p, apply)
        rel = p.relative_to(TEMPLATES).as_posix()
        if c:
            print(f"{rel}: converted {c}")
            total += c
        for u in unmapped:
            leftovers.append(f"{rel}: {u}")
    print(f"\nTotal converted: {total}")
    if leftovers:
        print(f"Leftovers ({len(leftovers)}):")
        for l in leftovers:
            print(f"  {l}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
