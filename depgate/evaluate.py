"""Evaluation: every backend on the labelled set, the raw answers and the full auto-merge policy.

Responses are replayed from `eval/cache/` so the numbers are reproducible offline (CI sets DEPGATE_OFFLINE=1).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backends import Backend, CacheMiss, get_backend
from .config import Config
from .metrics import accuracy, brier, macro_f1, percentile, prf, reliability
from .models import Decision, Update
from .policy import apply_policy
from .questions import DECISIONS, NOULS
from .usage import find_usage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "eval" / "data"
CACHE = ROOT / "eval" / "cache"
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
BACKEND_TITLES = {"jev": "Jev", "llm": "LLM (Gemini Flash-Lite)", "rules": "Semver rules"}


@dataclass
class Item:
    id: str
    update: Update
    gold: dict[str, Any]


def load_items(data_dir: Path = DATA) -> list[Item]:
    labels = {json.loads(line)["id"]: json.loads(line) for line in (data_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    items = []
    for line in (data_dir / "updates.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        lab = labels[row["id"]]
        update = Update.from_dict(row)
        update.usage = find_usage(update.package, update.ecosystem, update.release_notes, lab["repo_files"])
        items.append(Item(row["id"], update, lab["labels"]))
    return items


def run_backend(backend: Backend, items: list[Item], progress: bool = False) -> dict[str, Decision]:
    """Decisions by item id. Items with no recorded response (offline) are left out."""
    out: dict[str, Decision] = {}
    for i, item in enumerate(items, 1):
        try:
            out[item.id] = backend.decide(item.update)
        except CacheMiss:
            continue
        if progress and i % 20 == 0:
            print(f"  {backend.name}: {i}/{len(items)}", flush=True)
    return out


def policy_stats(items: list[Item], decisions: list[Decision], min_confidence: float) -> dict[str, float]:
    cfg = Config()
    cfg.auto_merge.min_confidence = min_confidence
    n = len(items)
    auto = safe = wrong = wrong_hold = human = 0
    for item, dec in zip(items, decisions, strict=True):
        out = apply_policy(item.update, dec, cfg)
        human += out.needs_human
        if out.action == "auto_merge":
            auto += 1
            gold = item.gold["decision"]
            safe += gold == "auto_merge"
            wrong += gold != "auto_merge"
            wrong_hold += gold == "hold"
    gold_auto = sum(1 for i in items if i.gold["decision"] == "auto_merge")
    return {
        "threshold": min_confidence,
        "auto_merged": auto,
        "auto_merged_share": auto / n,
        "safe": safe,
        "safe_share": safe / n,
        "safe_of_mergeable": safe / gold_auto if gold_auto else 0.0,
        "wrong": wrong,
        "wrong_hold": wrong_hold,
        "precision": safe / auto if auto else math.nan,
        "needs_human": human,
    }


def score_backend(items: list[Item], decisions: list[Decision]) -> dict[str, Any]:
    gold_dec = [i.gold["decision"] for i in items]
    pred_dec = [d.decision for d in decisions]
    res: dict[str, Any] = {
        "model": decisions[0].model if decisions else "",
        "n": len(items),
        "decision_accuracy": accuracy(gold_dec, pred_dec),
        "decision_macro_f1": macro_f1(gold_dec, pred_dec, list(DECISIONS)),
        "confusion": {g: {p: sum(1 for a, b in zip(gold_dec, pred_dec, strict=True) if a == g and b == p) for p in DECISIONS} for g in DECISIONS},
        "risk_accuracy": accuracy([i.gold["risk"] for i in items], [d.risk for d in decisions]),
        "risk_mae": sum(abs(i.gold["risk"] - d.risk) for i, d in zip(items, decisions, strict=True)) / len(items),
        "raw_unsafe": sum(1 for g, p in zip(gold_dec, pred_dec, strict=True) if g == "hold" and p == "auto_merge"),
        "nouls": {},
    }
    pooled_p: list[float] = []
    pooled_y: list[bool] = []
    for name in NOULS:
        gold = [bool(i.gold[name]) for i in items]
        probs = [float(d.answers[name].value) for d in decisions]
        p, r, f = prf(gold, [x >= 0.5 for x in probs])
        res["nouls"][name] = {
            "accuracy": accuracy(gold, [x >= 0.5 for x in probs]),
            "precision": p,
            "recall": r,
            "f1": f,
            "brier": brier(probs, gold),
            "positives": sum(gold),
        }
        pooled_p += probs
        pooled_y += gold
    top = [max(d.answers["decision"].probabilities.values()) for d in decisions]
    correct = [g == p for g, p in zip(gold_dec, pred_dec, strict=True)]
    res["decision_brier"] = brier(top, correct)
    res["noul_brier"] = brier(pooled_p, pooled_y)
    res["reliability_decision"] = reliability(top, correct)
    res["reliability_nouls"] = reliability([max(p, 1 - p) for p in pooled_p], [(p >= 0.5) == y for p, y in zip(pooled_p, pooled_y, strict=True)])
    holds = [i for i, it in enumerate(items) if it.gold["decision"] == "hold"]
    res["hold_caught"] = sum(1 for i in holds if pred_dec[i] == "hold") / len(holds) if holds else 0.0
    lat = [d.latency_ms for d in decisions]
    res["latency_p50_ms"] = percentile(lat, 0.5)
    res["latency_p95_ms"] = percentile(lat, 0.95)
    res["input_tokens_mean"] = sum(d.input_tokens for d in decisions) / len(decisions)
    res["output_tokens_mean"] = sum(d.output_tokens for d in decisions) / len(decisions)
    res["input_tokens_total"] = sum(d.input_tokens for d in decisions)
    res["output_tokens_total"] = sum(d.output_tokens for d in decisions)
    res["cost_per_1000_usd"] = 1000 * sum(d.cost_usd for d in decisions) / len(decisions)
    res["policy"] = [policy_stats(items, decisions, t) for t in THRESHOLDS]
    res["policy_default"] = policy_stats(items, decisions, Config().auto_merge.min_confidence)
    return res


def evaluate(backends: list[str], progress: bool = False) -> dict[str, Any]:
    items = load_items()
    gold = [i.gold for i in items]
    out: dict[str, Any] = {
        "n": len(items),
        "label_counts": {
            "decision": {k: sum(1 for g in gold if g["decision"] == k) for k in DECISIONS},
            **{k: sum(1 for g in gold if g[k]) for k in NOULS},
            "major": sum(1 for i in items if i.update.jump == "major"),
            "ecosystems": {e: sum(1 for i in items if i.update.ecosystem == e) for e in ("npm", "pip")},
        },
        "backends": {},
        "partial": {},
        "subset": None,
        "skipped": [],
    }
    runs: dict[str, dict[str, Decision]] = {}
    for name in backends:
        got = run_backend(get_backend(name, cache_dir=CACHE), items, progress)
        if not got:
            out["skipped"].append(name)
            continue
        runs[name] = got
        if len(got) == len(items):
            out["backends"][name] = score_backend(items, [got[i.id] for i in items])
        else:
            out["partial"][name] = len(got)
    if out["partial"]:
        common = [i for i in items if all(i.id in got for got in runs.values())]
        out["subset"] = {"n": len(common), "backends": {name: score_backend(common, [got[i.id] for i in common]) for name, got in runs.items()}}
    return out


def _pct(x: float) -> str:
    return "n/a" if isinstance(x, float) and math.isnan(x) else f"{100 * x:.1f}%"


def _tables(b: dict[str, Any], h: str) -> list[str]:
    """Headline, thresholds, per-question, calibration and cost tables for a set of backends."""
    names = list(b)
    head = "| | " + " | ".join(BACKEND_TITLES.get(n, n) for n in names) + " |"
    sep = "|---|" + "---|" * len(names)

    def row(label: str, fn: Any) -> str:
        return f"| {label} | " + " | ".join(fn(b[n]) for n in names) + " |"

    lines = [
        f"{h} Headline: the auto-merge policy",
        "",
        "Default policy: auto-merge only when the backend chooses auto-merge with confidence of at least 0.8, risk is at most 1, CI is green, the bump is not major and no breaking change touches the repository.",
        "",
        head,
        sep,
        row("PRs safely auto-merged (share of all PRs)", lambda r: f"{r['policy_default']['safe']} ({_pct(r['policy_default']['safe_share'])})"),
        row("Share of the safe-to-merge PRs it auto-merged", lambda r: _pct(r["policy_default"]["safe_of_mergeable"])),
        row("Wrongly auto-merged (gold: review or hold)", lambda r: str(r["policy_default"]["wrong"])),
        row("Wrongly auto-merged that should be held", lambda r: str(r["policy_default"]["wrong_hold"])),
        row("Breaking-change recall (notes)", lambda r: _pct(r["nouls"]["breaking_in_notes"]["recall"])),
        row("Breaking-change-affects-repo recall", lambda r: _pct(r["nouls"]["breaking_affects_repo"]["recall"])),
        row("Held PRs caught as hold (raw answer)", lambda r: _pct(r["hold_caught"])),
        "",
        f"{h} Automation at different confidence thresholds",
        "",
        "Same policy, changing only the minimum decision confidence for auto-merge. *Safe* means the gold decision was auto-merge; *wrong* means it was review or hold.",
        "",
    ]
    for n in names:
        lines += [
            f"**{BACKEND_TITLES.get(n, n)}**",
            "",
            "| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |",
            "|---|---|---|---|---|---|",
        ]
        for p in b[n]["policy"]:
            lines.append(
                f"| {p['threshold']:.2f} | {p['auto_merged']} ({_pct(p['auto_merged_share'])}) | {p['safe']} | {p['wrong']} | {p['wrong_hold']} | {_pct(p['precision'])} |"
            )
        lines.append("")
    lines += [
        f"{h} Per-question quality",
        "",
        head,
        sep,
        row("Decision accuracy", lambda r: _pct(r["decision_accuracy"])),
        row("Decision macro-F1", lambda r: f"{r['decision_macro_f1']:.3f}"),
        row("Raw answer auto-merge when gold is hold", lambda r: str(r["raw_unsafe"])),
        row("Risk level exact accuracy", lambda r: _pct(r["risk_accuracy"])),
        row("Risk level mean absolute error", lambda r: f"{r['risk_mae']:.2f}"),
    ]
    for name in NOULS:
        lines.append(row(f"`{name}` accuracy / F1", lambda r, nm=name: f"{_pct(r['nouls'][nm]['accuracy'])} / {r['nouls'][nm]['f1']:.3f}"))
    lines += ["", "Decision confusion (rows: gold, columns: predicted auto merge / review / hold):", ""]
    for n in names:
        conf = b[n]["confusion"]
        cells = "; ".join(f"{g.replace('_', ' ')}: " + " / ".join(str(conf[g][p]) for p in DECISIONS) for g in DECISIONS)
        lines.append(f"- {BACKEND_TITLES.get(n, n)}: {cells}")
    lines += [
        "",
        f"{h} Calibration",
        "",
        "Brier score: the mean squared gap between the stated probability and what was true (lower is better; 0.25 is a coin flip).",
        "",
        head,
        sep,
        row("Brier, decision (top probability vs correct)", lambda r: f"{r['decision_brier']:.3f}"),
        row("Brier, the four yes/no questions pooled", lambda r: f"{r['noul_brier']:.3f}"),
        "",
        "Reliability of the decision answer: stated top probability vs how often it was right.",
        "",
        "| Bin | " + " | ".join(f"{BACKEND_TITLES.get(n, n)} (n, stated, observed)" for n in names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for k in range(len(b[names[0]]["reliability_decision"])):
        rel_cells: list[str] = []
        for n in names:
            _, cnt, stated, obs = b[n]["reliability_decision"][k]
            rel_cells.append("-" if cnt == 0 else f"{cnt}, {stated:.2f}, {obs:.2f}")
        lines.append(f"| {b[names[0]]['reliability_decision'][k][0]} | " + " | ".join(rel_cells) + " |")
    lines += [
        "",
        f"{h} Speed and cost",
        "",
        head,
        sep,
        row("Latency p50", lambda r: f"{r['latency_p50_ms']:.0f} ms"),
        row("Latency p95", lambda r: f"{r['latency_p95_ms']:.0f} ms"),
        row("Input tokens per PR (mean)", lambda r: f"{r['input_tokens_mean']:.0f}"),
        row("Output tokens per PR (mean)", lambda r: f"{r['output_tokens_mean']:.0f}"),
        row("Cost per 1,000 PRs", lambda r: f"${r['cost_per_1000_usd']:.4f}"),
        "",
    ]
    return lines


def render_markdown(res: dict[str, Any]) -> str:
    lc = res["label_counts"]
    lines = [
        "# Evaluation results",
        "",
        f"{res['n']} real dependency updates ({lc['ecosystems']['npm']} npm, {lc['ecosystems']['pip']} PyPI; {lc['major']} major bumps) with their public release notes,",
        "labelled by the rules in [LABELLING.md](LABELLING.md). Gold decisions: "
        + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in lc["decision"].items())
        + f". Breaking change in the notes: {lc['breaking_in_notes']}; affecting the repository: {lc['breaking_affects_repo']}; security fixes: {lc['security_fix']}.",
        "",
        "Every number below comes from recorded real API responses (`eval/cache/`), replayed by `depgate eval`.",
        "",
    ]
    if res["backends"]:
        names = ", ".join(BACKEND_TITLES.get(n, n) for n in res["backends"])
        lines += [f"## All {res['n']} updates: {names}", ""]
        lines += _tables(res["backends"], "###")
    if res.get("subset"):
        sub = res["subset"]
        partial = ", ".join(f"{BACKEND_TITLES.get(n, n)} was measured on {k} of the {res['n']} updates" for n, k in res["partial"].items())
        lines += [
            f"## All three backends on the {sub['n']} updates every backend answered",
            "",
            f"{partial} (the free-tier daily request quota of its API), so this section compares every backend on the same {sub['n']} updates.",
            "",
        ]
        lines += _tables(sub["backends"], "###")
    lines += [
        "Jev pricing: $0.042 per million input tokens, output free. The LLM cost uses an assumed list price of $0.10 / $0.40 per million input / output tokens",
        "for the default model (the evaluation ran on a free tier). The rules baseline makes no API call.",
    ]
    if res["skipped"]:
        lines += ["", f"Not run (no cached responses and no key): {', '.join(res['skipped'])}."]
    return "\n".join(lines) + "\n"


def write_results(res: dict[str, Any], out_dir: Path = ROOT / "eval") -> Path:
    (out_dir / "results.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    path = out_dir / "results.md"
    path.write_text(render_markdown(res), encoding="utf-8", newline="\n")
    return path
