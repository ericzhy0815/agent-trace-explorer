"""Keep only the analysis set in the packed explorer: one scored run per model, task and condition
(data/agent-runs-20261020/analysis_set.csv, written from figures/scripts/common_runs.py), and recompute the
within-task percentiles among those runs. Usage: python filter_analysis_set.py <packed_site_dir>"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

SITE = Path(sys.argv[1]); HERE = Path(__file__).resolve().parent
keep = {r["run_id"] for r in csv.DictReader(open(HERE.parent / "analysis_set.csv"))}
runs = [r for r in json.loads((SITE / "data" / "runs.json").read_text()) if r["id"] in keep]

def pct(rs, key, low_is_better=False):
    vals = sorted(x[key] for x in rs)
    for x in rs:
        lo = sum(v < x[key] for v in vals); eq = sum(v == x[key] for v in vals)
        p = (lo + (eq - 1) / 2) / max(1, len(vals) - 1)
        x["mae_pct" if low_is_better else "pct"] = round(1 - p if low_is_better else p, 4)

by, by_mae = defaultdict(list), defaultdict(list)
for r in runs:
    if r.get("score") is not None: by[r["task"]].append(r)
    if r.get("mae") is not None: by_mae[r["task"]].append(r)
for rs in by.values(): pct(rs, "score")
for rs in by_mae.values(): pct(rs, "mae", low_is_better=True)
# the paper-wide within-task percentile ('pct') is on the primary metric: coordinate error on the tasks with true
# positions (any run has an MAE), otherwise the overall score (figures/scripts/common_runs.within_task_pct)
for t, rs in by_mae.items():
    for x in rs: x["pct_overall"] = x.get("pct")
    pct(rs, "mae", low_is_better=True)
    for x in rs: x["pct"] = x["mae_pct"]
(SITE / "data" / "runs.json").write_text(json.dumps(runs, separators=(",", ":")))
tasks = json.loads((SITE / "data" / "tasks.json").read_text())
for t, v in tasks.items(): v["n_scored"] = len(by.get(t, []))
(SITE / "data" / "tasks.json").write_text(json.dumps(tasks, separators=(",", ":")))
c = defaultdict(int)
for r in runs: c[(r["model"], r["cond"])] += 1
print(len(runs), dict(c))
