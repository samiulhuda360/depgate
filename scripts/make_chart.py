"""Draws the headline chart (docs/build/chart.html) from eval/results.json: PRs safely and wrongly auto-merged."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLES = {"rules": "Semver rules", "jev": "Jev", "llm": "LLM (Gemini Flash-Lite)"}
SAFE, WRONG = "#008f7e", "#c4622d"


def main() -> None:
    res = json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))
    group = res["subset"] or {"n": res["n"], "backends": res["backends"]}  # the set every backend answered
    rows = [(TITLES[k], v["policy_default"]) for k, v in group["backends"].items()]
    n = group["n"]
    first = rows[0][1]
    gold_auto = round(first["safe"] / first["safe_of_mergeable"]) if first["safe_of_mergeable"] else 0
    width, left, bar, gap, step = 860, 230, 22, 4, 78
    scale = (width - left - 90) / gold_auto
    height = 60 + step * len(rows)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Safely and wrongly auto-merged pull requests per backend">'
    ]
    y = 60
    for title, p in rows:
        parts.append(f'<text x="{left - 14}" y="{y + bar + 2}" text-anchor="end" class="name">{title}</text>')
        for i, (value, color, label) in enumerate(((p["safe"], SAFE, "safely auto-merged"), (p["wrong"], WRONG, "wrongly auto-merged"))):
            by = y + i * (bar + gap)
            w = max(value * scale, 2)
            parts.append(f'<rect x="{left}" y="{by}" width="{w:.1f}" height="{bar}" rx="4" fill="{color}"><title>{title}: {value} {label}</title></rect>')
            parts.append(f'<text x="{left + w + 8:.1f}" y="{by + 16}" class="val">{value}</text>')
        y += step
    axis_y = y - 10
    parts.append(f'<line x1="{left}" x2="{left}" y1="50" y2="{axis_y}" class="axis"/>')
    parts.append("</svg>")
    legend = f'<span class="sw" style="background:{SAFE}"></span>Safely auto-merged <span class="sw" style="background:{WRONG};margin-left:18px"></span>Wrongly auto-merged (should have been reviewed or held)'
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>depgate results</title><style>
body{{margin:0;padding:24px;background:#fcfcfb;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1d2b29}}
h1{{font-size:20px;margin:0 0 6px}} .legend{{font-size:14px;color:#3d4f4c;margin:0 0 6px}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
.name{{font-size:15px;fill:#1d2b29}} .val{{font-size:14px;fill:#3d4f4c}} .note{{font-size:13px;fill:#5f7471}} .axis{{stroke:#9aa9a6;stroke-width:1}} .foot{{font-size:13px;color:#5f7471;margin:6px 0 0}}
</style></head><body><h1>Auto-merging dependency updates: what each gate let through</h1><div class="legend">{legend}</div>{"".join(parts)}<p class="foot">{n} real updates, {gold_auto} of them safe to auto-merge. Default policy: decision confidence at least 0.8, risk at most 1, CI green, no major bumps.</p></body></html>"""
    out = ROOT / "docs" / "build" / "chart.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
