# Evaluation results

199 real dependency updates (116 npm, 83 PyPI; 69 major bumps) with their public release notes,
labelled by the rules in [LABELLING.md](LABELLING.md). Gold decisions: auto merge 92, merge after review 62, hold 45. Breaking change in the notes: 61; affecting the repository: 30; security fixes: 47.

Every number below comes from recorded real API responses (`eval/cache/`), replayed by `depgate eval`.

## All 199 updates: Semver rules, Jev

### Headline: the auto-merge policy

Default policy: auto-merge only when the backend chooses auto-merge with confidence of at least 0.8, risk is at most 1, CI is green, the bump is not major and no breaking change touches the repository.

| | Semver rules | Jev |
|---|---|---|
| PRs safely auto-merged (share of all PRs) | 92 (46.2%) | 50 (25.1%) |
| Share of the safe-to-merge PRs it auto-merged | 100.0% | 54.3% |
| Wrongly auto-merged (gold: review or hold) | 15 | 0 |
| Wrongly auto-merged that should be held | 6 | 0 |
| Breaking-change recall (notes) | 68.9% | 98.4% |
| Breaking-change-affects-repo recall | 73.3% | 86.7% |
| Held PRs caught as hold (raw answer) | 62.2% | 84.4% |

### Automation at different confidence thresholds

Same policy, changing only the minimum decision confidence for auto-merge. *Safe* means the gold decision was auto-merge; *wrong* means it was review or hold.

**Semver rules**

| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |
|---|---|---|---|---|---|
| 0.50 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |
| 0.60 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |
| 0.70 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |
| 0.80 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |
| 0.90 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |
| 0.95 | 107 (53.8%) | 92 | 15 | 6 | 86.0% |

**Jev**

| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |
|---|---|---|---|---|---|
| 0.50 | 68 (34.2%) | 68 | 0 | 0 | 100.0% |
| 0.60 | 65 (32.7%) | 65 | 0 | 0 | 100.0% |
| 0.70 | 62 (31.2%) | 62 | 0 | 0 | 100.0% |
| 0.80 | 50 (25.1%) | 50 | 0 | 0 | 100.0% |
| 0.90 | 36 (18.1%) | 36 | 0 | 0 | 100.0% |
| 0.95 | 21 (10.6%) | 21 | 0 | 0 | 100.0% |

### Per-question quality

| | Semver rules | Jev |
|---|---|---|
| Decision accuracy | 60.3% | 88.9% |
| Decision macro-F1 | 0.440 | 0.884 |
| Raw answer auto-merge when gold is hold | 17 | 1 |
| Risk level exact accuracy | 46.2% | 88.9% |
| Risk level mean absolute error | 0.70 | 0.12 |
| `breaking_in_notes` accuracy / F1 | 76.9% / 0.646 | 92.5% / 0.889 |
| `breaking_affects_repo` accuracy / F1 | 72.4% / 0.444 | 88.9% / 0.703 |
| `security_fix` accuracy / F1 | 98.5% / 0.967 | 99.5% / 0.989 |
| `runtime_change` accuracy / F1 | 91.0% / 0.000 | 92.5% / 0.706 |

Decision confusion (rows: gold, columns: predicted auto merge / review / hold):

- Semver rules: auto merge: 92 / 0 / 0; merge after review: 21 / 0 / 41; hold: 17 / 0 / 28
- Jev: auto merge: 85 / 6 / 1; merge after review: 6 / 54 / 2; hold: 1 / 6 / 38

### Calibration

Brier score: the mean squared gap between the stated probability and what was true (lower is better; 0.25 is a coin flip).

| | Semver rules | Jev |
|---|---|---|
| Brier, decision (top probability vs correct) | 0.397 | 0.088 |
| Brier, the four yes/no questions pooled | 0.100 | 0.052 |

Reliability of the decision answer: stated top probability vs how often it was right.

| Bin | Semver rules (n, stated, observed) | Jev (n, stated, observed) |
|---|---|---|
| 0.0-0.5 | - | 11, 0.46, 0.55 |
| 0.5-0.6 | - | 23, 0.55, 0.74 |
| 0.6-0.7 | - | 22, 0.65, 0.68 |
| 0.7-0.8 | - | 22, 0.75, 0.91 |
| 0.8-0.9 | - | 31, 0.84, 0.94 |
| 0.9-1.0 | 199, 1.00, 0.60 | 90, 0.96, 1.00 |

### Speed and cost

| | Semver rules | Jev |
|---|---|---|
| Latency p50 | 0 ms | 483 ms |
| Latency p95 | 0 ms | 659 ms |
| Input tokens per PR (mean) | 0 | 1444 |
| Output tokens per PR (mean) | 0 | 127 |
| Cost per 1,000 PRs | $0.0000 | $0.0607 |

## All three backends on the 146 updates every backend answered

LLM (Gemini Flash-Lite) was measured on 146 of the 199 updates (the free-tier daily request quota of its API), so this section compares every backend on the same 146 updates.

### Headline: the auto-merge policy

Default policy: auto-merge only when the backend chooses auto-merge with confidence of at least 0.8, risk is at most 1, CI is green, the bump is not major and no breaking change touches the repository.

| | Semver rules | Jev | LLM (Gemini Flash-Lite) |
|---|---|---|---|
| PRs safely auto-merged (share of all PRs) | 66 (45.2%) | 35 (24.0%) | 52 (35.6%) |
| Share of the safe-to-merge PRs it auto-merged | 100.0% | 53.0% | 78.8% |
| Wrongly auto-merged (gold: review or hold) | 10 | 0 | 0 |
| Wrongly auto-merged that should be held | 4 | 0 | 0 |
| Breaking-change recall (notes) | 69.0% | 97.6% | 97.6% |
| Breaking-change-affects-repo recall | 75.0% | 90.0% | 90.0% |
| Held PRs caught as hold (raw answer) | 58.1% | 87.1% | 83.9% |

### Automation at different confidence thresholds

Same policy, changing only the minimum decision confidence for auto-merge. *Safe* means the gold decision was auto-merge; *wrong* means it was review or hold.

**Semver rules**

| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |
|---|---|---|---|---|---|
| 0.50 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |
| 0.60 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |
| 0.70 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |
| 0.80 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |
| 0.90 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |
| 0.95 | 76 (52.1%) | 66 | 10 | 4 | 86.8% |

**Jev**

| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |
|---|---|---|---|---|---|
| 0.50 | 48 (32.9%) | 48 | 0 | 0 | 100.0% |
| 0.60 | 46 (31.5%) | 46 | 0 | 0 | 100.0% |
| 0.70 | 44 (30.1%) | 44 | 0 | 0 | 100.0% |
| 0.80 | 35 (24.0%) | 35 | 0 | 0 | 100.0% |
| 0.90 | 26 (17.8%) | 26 | 0 | 0 | 100.0% |
| 0.95 | 16 (11.0%) | 16 | 0 | 0 | 100.0% |

**LLM (Gemini Flash-Lite)**

| Min confidence | Auto-merged | Safe | Wrong | Wrong (should hold) | Precision |
|---|---|---|---|---|---|
| 0.50 | 64 (43.8%) | 62 | 2 | 0 | 96.9% |
| 0.60 | 64 (43.8%) | 62 | 2 | 0 | 96.9% |
| 0.70 | 64 (43.8%) | 62 | 2 | 0 | 96.9% |
| 0.80 | 52 (35.6%) | 52 | 0 | 0 | 100.0% |
| 0.90 | 43 (29.5%) | 43 | 0 | 0 | 100.0% |
| 0.95 | 25 (17.1%) | 25 | 0 | 0 | 100.0% |

### Per-question quality

| | Semver rules | Jev | LLM (Gemini Flash-Lite) |
|---|---|---|---|
| Decision accuracy | 57.5% | 91.1% | 89.0% |
| Decision macro-F1 | 0.420 | 0.905 | 0.887 |
| Raw answer auto-merge when gold is hold | 13 | 1 | 0 |
| Risk level exact accuracy | 43.2% | 89.0% | 82.9% |
| Risk level mean absolute error | 0.75 | 0.12 | 0.19 |
| `breaking_in_notes` accuracy / F1 | 76.0% / 0.624 | 90.4% / 0.854 | 83.6% / 0.774 |
| `breaking_affects_repo` accuracy / F1 | 71.9% / 0.423 | 89.0% / 0.692 | 93.8% / 0.800 |
| `security_fix` accuracy / F1 | 98.6% / 0.968 | 99.3% / 0.984 | 100.0% / 1.000 |
| `runtime_change` accuracy / F1 | 91.1% / 0.000 | 92.5% / 0.703 | 92.5% / 0.703 |

Decision confusion (rows: gold, columns: predicted auto merge / review / hold):

- Semver rules: auto merge: 66 / 0 / 0; merge after review: 16 / 0 / 33; hold: 13 / 0 / 18
- Jev: auto merge: 62 / 3 / 1; merge after review: 3 / 44 / 2; hold: 1 / 3 / 27
- LLM (Gemini Flash-Lite): auto merge: 62 / 4 / 0; merge after review: 6 / 42 / 1; hold: 0 / 5 / 26

### Calibration

Brier score: the mean squared gap between the stated probability and what was true (lower is better; 0.25 is a coin flip).

| | Semver rules | Jev | LLM (Gemini Flash-Lite) |
|---|---|---|---|
| Brier, decision (top probability vs correct) | 0.425 | 0.082 | 0.096 |
| Brier, the four yes/no questions pooled | 0.099 | 0.055 | 0.073 |

Reliability of the decision answer: stated top probability vs how often it was right.

| Bin | Semver rules (n, stated, observed) | Jev (n, stated, observed) | LLM (Gemini Flash-Lite) (n, stated, observed) |
|---|---|---|---|
| 0.0-0.5 | - | 9, 0.45, 0.67 | - |
| 0.5-0.6 | - | 18, 0.55, 0.78 | - |
| 0.6-0.7 | - | 14, 0.65, 0.71 | - |
| 0.7-0.8 | - | 18, 0.74, 0.89 | 2, 0.70, 1.00 |
| 0.8-0.9 | - | 19, 0.84, 1.00 | 24, 0.82, 0.67 |
| 0.9-1.0 | 146, 1.00, 0.58 | 68, 0.96, 1.00 | 120, 0.98, 0.93 |

### Speed and cost

| | Semver rules | Jev | LLM (Gemini Flash-Lite) |
|---|---|---|---|
| Latency p50 | 0 ms | 485 ms | 1540 ms |
| Latency p95 | 0 ms | 694 ms | 15498 ms |
| Input tokens per PR (mean) | 0 | 1460 | 1387 |
| Output tokens per PR (mean) | 0 | 127 | 142 |
| Cost per 1,000 PRs | $0.0000 | $0.0613 | $0.1956 |

Jev pricing: $0.042 per million input tokens, output free. The LLM cost uses an assumed list price of $0.10 / $0.40 per million input / output tokens
for the default model (the evaluation ran on a free tier). The rules baseline makes no API call.
