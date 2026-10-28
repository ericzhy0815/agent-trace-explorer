"""Write data/methods.json for the explorer's "Published methods" tab.

Every baseline configuration in scores/baseline_scores.csv (with the spatial MNN scores joined, as in
figures/scripts/common_runs.py), grouped as published / naive / program (synth_*) / label-using (*truelabels*), and,
per task, the analysis-set agent runs (one per model and condition) on the same metrics.

Usage (from the project root): python data/agent-runs-20261020/explorer/build_methods_json.py <site_dir>
"""
import json, math, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "figures" / "scripts"))
from common_runs import baseline_scores, agent_scores, NAIVE  # noqa: E402

SITE = Path(sys.argv[1]).resolve()
PKG = {"cast": "CAST", "paste2": "PASTE2", "paste": "PASTE", "spateo": "Spateo", "santo": "SANTO", "staligner": "STAligner",
       "stalign": "STalign", "slat": "SLAT", "geaso": "GEASO", "moscot": "Moscot", "stair": "STAIR", "spacel": "SPACEL", "gpsa": "GPSA"}
# metric columns, in the order the page reads them
COLS = ["score_overall_mean", "score_mae", "ex", "score_matching_accuracy", "score_overlap_ratio_region", "mnn_label_accuracy",
        "mnn_expression_cosine"]


def package(method):
    m = method.lower()
    for k in sorted(PKG, key=len, reverse=True):          # staligner before stalign, paste2 before paste
        if m == k or m.startswith(k + "_"): return PKG[k]
    return method


def group(method, variant):
    if method in NAIVE: return "naive"
    if method.startswith("synth_"): return "program"
    if "truelabels" in variant: return "label-using"
    return "published"


def num(v, d=4):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), d)


b = baseline_scores()
_, s = agent_scores()
tasks = {}
for t, g in b.groupby("task"):
    rows = []
    for _, r in g.iterrows():
        grp = group(r.method, r.variant)
        pkg = r.method if grp in ("naive", "program") else package(r.method)
        rows.append([pkg, r.variant, grp, num(r.runtime_s, 1)] + [num(r[c]) for c in COLS])
    ag = s[s.task == t]
    tasks[t] = dict(
        f=g.family.iloc[0],
        t=bool(g.score_mae.notna().any() or ag.score_mae.notna().any()),
        l=bool(g.score_matching_accuracy.notna().any() or g.mnn_label_accuracy.notna().any()),
        c=rows,
        a=[[r.model, r.condition] + [num(r[c]) for c in COLS] + [r.run_id] for _, r in ag.iterrows()])
out = dict(cols=["package", "variant", "group", "runtime_s"] + COLS, agent_cols=["model", "condition"] + COLS + ["run_id"], tasks=tasks)
(SITE / "data").mkdir(parents=True, exist_ok=True)
p = SITE / "data" / "methods.json"
p.write_text(json.dumps(out, separators=(",", ":")))
n_cfg = sum(len(v["c"]) for v in tasks.values())
print(f"wrote {p} ({os.path.getsize(p) / 1e6:.2f} MB): {len(tasks)} tasks, {n_cfg} configurations, "
      f"{sum(len(v['a']) for v in tasks.values())} agent runs")
