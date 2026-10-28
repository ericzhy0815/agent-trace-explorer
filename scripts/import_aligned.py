"""Bring the aligned-result figures (plot_aligned_results.py output) into the explorer.

Copies <src>/<task>/*.jpg to explorer/aligned/<task>/ and merges every <task>/summary.json into
explorer/data/aligned.json, with each drawn run's cluster path turned into the explorer run_id
(<run_dir>__<array_task>). Panels whose run is not in the bundle keep run_id = null.

Usage (from the bundle root): python explorer/import_aligned.py <aligned_figures_dir>
"""
import json, shutil, sys
from pathlib import Path

ROOT = Path(".").resolve(); SRC = Path(sys.argv[1]).expanduser().resolve()
DST = ROOT / "explorer" / "aligned"
ids = {r["id"] for r in json.loads((ROOT / "explorer" / "data" / "runs.json").read_text())}
if DST.exists(): shutil.rmtree(DST)
out, n_img, n_run, n_missing = {}, 0, 0, 0
for d in sorted(p for p in SRC.iterdir() if p.is_dir() and (p / "summary.json").exists()):
    s = json.loads((d / "summary.json").read_text())
    (DST / d.name).mkdir(parents=True)
    figs = []
    for f in s.get("figures", []):
        if (d / f).exists() and f.lower().endswith((".jpg", ".jpeg", ".png")):
            shutil.copy(d / f, DST / d.name / f); figs.append(f); n_img += 1
    rows = []
    for row in s.get("panels", []):
        prow = []
        for p in row:
            rid = None
            if p.get("run"):
                parts = Path(p["run"]).parts          # .../cluster/<array_task>/<run_dir>
                rid = f"{parts[-1]}__{parts[-2]}" if len(parts) >= 2 else None
                if rid in ids: n_run += 1
                else: n_missing += 1; rid = None
            prow.append(dict(title=p.get("title", ""), score=p.get("score", ""), drawn=bool(p.get("drawn")), run_id=rid))
        rows.append(prow)
    out[d.name] = dict(metric=s.get("metric"), truth=s.get("truth"), labels=s.get("labels"), n_slices=s.get("n_slices"),
                       figures=figs, panels=rows, baselines=s.get("baselines", {}), agents=s.get("agents", {}))
(ROOT / "explorer" / "data" / "aligned.json").write_text(json.dumps(out, separators=(",", ":")))
readme = SRC / "README.md"
if readme.exists(): shutil.copy(readme, DST / "README.md")
print(f"{len(out)} tasks, {n_img} images; {n_run} drawn runs linked to the bundle, {n_missing} not found")
