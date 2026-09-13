"""Print per-file uncovered lines/branch arms from vitest v8 coverage JSON."""

import json
import os
import sys

p = os.path.join("coverage-js", "coverage-final.json")
d = json.load(open(p, encoding="utf-8"))
want = sys.argv[1:] or ["ai-chat.js", "video_player.js", "ui.js", "toast.js", "api.js", "index.js"]
for k, v in sorted(d.items()):
    short = k.replace("\\", "/").split("/js/")[-1]
    if short in want:
        lines = sorted(int(i) for i, c in v.get("s", {}).items() if c == 0)
        missed_b = []
        for b, cnt in v.get("b", {}).items():
            for arm, c in enumerate(cnt):
                if c == 0:
                    missed_b.append(f"{b}[{arm}]")
        print(short, "-> missed lines:", lines)
        print("   missed branch arms:", len(missed_b), missed_b[:20])
