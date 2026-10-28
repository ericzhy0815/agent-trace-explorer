"""Redraw every aligned-result panel on its own, matched to model and method (alignment explorer).

Input: the folder written on the cluster by explorer/cluster/export_aligned_points.py
       (<points>/<task>/{cells.csv.gz, points.csv.gz, panels.json}).
For each task and each figure pair (reference, moving section), every panel (input, ground truth, baselines,
each model's best and median bare run) is drawn as an overlay: the reference section as faint discs, the moving
section as dots, coloured by region label (labels the agents never saw); sections without labels are blue and orange.
Outputs, on transparent backgrounds:
    explorer/aligned_runs/<task>/<pair>/<panel>.png            map only
    explorer/aligned_runs/<task>/<pair>/<panel>_labelled.png   with model, condition, method and score
    explorer/aligned_runs/<task>/<pair>/sprite.png             all panels of the pair, for the hosted explorer
    explorer/data/aligned_maps.json                            tile positions, titles, run ids, label colours

Usage: uv run --no-project --with matplotlib --with numpy --with pandas --with pillow \
           python explorer/render_aligned.py <points_dir> [task ...]
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

PTS = Path(sys.argv[1]).expanduser().resolve(); ONLY = set(sys.argv[2:])
EX = Path(__file__).resolve().parent; OUT = EX / "aligned_runs"; OUT.mkdir(exist_ok=True)
runs = {r["id"]: r for r in json.loads((EX / "data" / "runs.json").read_text())}
LABEL = {"claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-sonnet-4-6": "Claude Sonnet 4.6",
         "gpt-6-astra": "GPT-6 Astra", "gpt-5.5": "GPT-5.5", "gemini-3.5-flash": "Gemini 3.5 Flash"}
MCOL = {"claude-opus-5-5": "#0E4F4C", "claude-sonnet-5-5": "#2B8C87", "claude-sonnet-4-6": "#3E8F88", "gpt-6-astra": "#B5651D", "gpt-5.5": "#B98420", "gemini-3.5-flash": "#1F5AA6"}
# High-contrast label colours (the 8 most frequent labels of a task); other labels are drawn light gray underneath.
PAL = ["#E41A1C", "#377EB8", "#4DAF4A", "#984EA3", "#FF7F00", "#A65628", "#F781BF", "#1B9E77"]
OTHER = "#D0D0D0"
TILE, DPI = 420, 150


def run_of(path):
    if not path: return None
    p = Path(path); rid = f"{p.name}__{p.parent.name}"      # <run_dir>__<array_task>, as in the bundle
    return runs.get(rid)


def approach_text(a):
    a = a or ""
    return a[4:] if a.startswith("pkg:") else a.replace("custom:", "own ")


def draw(ref, mov, path, size_px, title=None, sub=None, title_color="#272727"):
    allxy = np.vstack([ref[0], mov[0]]) if len(ref[0]) and len(mov[0]) else (ref[0] if len(ref[0]) else mov[0])
    figw = size_px / DPI; extra = 0.42 if title else 0
    fig = plt.figure(figsize=(figw, figw + extra), dpi=DPI)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96 * figw / (figw + extra)])
    n = max(1, len(allxy))
    s_mov = max(0.2, min(5.0, 1.2e4 / n)); s_ref = s_mov * 3.2
    if len(ref[0]): ax.scatter(ref[0][:, 0], ref[0][:, 1], c=ref[1], s=s_ref, alpha=0.22, linewidths=0, rasterized=True)
    if len(mov[0]): ax.scatter(mov[0][:, 0], mov[0][:, 1], c=mov[1], s=s_mov, linewidths=0, rasterized=True)
    ax.set_aspect("equal"); ax.axis("off")
    if len(allxy):
        lo, hi = np.nanpercentile(allxy, 0.5, axis=0), np.nanpercentile(allxy, 99.5, axis=0); pad = 0.04 * np.nanmax(hi - lo)
        ax.set_xlim(lo[0] - pad, hi[0] + pad); ax.set_ylim(hi[1] + pad, lo[1] - pad)
    if title:
        fig.text(0.03, 0.985, title, ha="left", va="top", fontsize=7.5, fontweight="bold", color=title_color)
        if sub: fig.text(0.03, 0.985 - 0.17 / (figw + extra), sub, ha="left", va="top", fontsize=6, color="#444444")
    fig.savefig(path, transparent=True, dpi=DPI); plt.close(fig)


index = {}
for tdir in sorted(p for p in PTS.iterdir() if (p / "panels.json").exists()):
    task = tdir.name
    if ONLY and task not in ONLY: continue
    meta = json.loads((tdir / "panels.json").read_text())
    cells = pd.read_csv(tdir / "cells.csv.gz", dtype={"slice": str, "obs_id": str, "label": str}).fillna({"label": ""})
    pts = pd.read_csv(tdir / "points.csv.gz", dtype={"panel": str, "slice": str, "obs_id": str})
    labs = [l for l in cells.label.value_counts().index if l]
    lcol = {l: (PAL[i] if i < len(PAL) else OTHER) for i, l in enumerate(labs)}   # labs: most frequent first
    has_labels = bool(labs)
    task_idx = dict(pairs=[], labels=[dict(name=l, color=lcol[l]) for l in labs], metric=meta.get("metric"))
    for pi, (ref_id, mov_id) in enumerate(meta.get("pairs", [])):
        pname = f"pair{pi + 1:02d}"; pdir = OUT / task / pname; pdir.mkdir(parents=True, exist_ok=True)
        cref = cells[cells.slice == ref_id].set_index("obs_id"); cmov = cells[cells.slice == mov_id].set_index("obs_id")
        def colours(c, which):
            if has_labels: return c.label.map(lambda l: lcol.get(l, "#D0D0D0")).to_numpy()
            return np.full(len(c), "#2A78D6" if which == "ref" else "#EB6834")
        tiles = []
        for p in meta["panels"]:
            if p["kind"] == "input":
                ref = (cref[["x_in", "y_in"]].to_numpy(float), colours(cref, "ref")); mov = (cmov[["x_in", "y_in"]].to_numpy(float), colours(cmov, "mov"))
            elif p["kind"] == "truth":
                if cref.x_gt.isna().all(): continue
                ref = (cref[["x_gt", "y_gt"]].to_numpy(float), colours(cref, "ref")); mov = (cmov[["x_gt", "y_gt"]].to_numpy(float), colours(cmov, "mov"))
            else:
                q = pts[pts.panel == p["key"]]
                if q.empty: continue
                qr = q[q.slice == ref_id].set_index("obs_id"); qm = q[q.slice == mov_id].set_index("obs_id")
                ref = (qr[["x", "y"]].to_numpy(float), colours(cref.reindex(qr.index), "ref")); mov = (qm[["x", "y"]].to_numpy(float), colours(cmov.reindex(qm.index), "mov"))
            r = run_of(p.get("run")) if p["kind"] == "run" else None
            if r:
                model = r["model"]; title = f"{LABEL.get(model, model)} · {r['cond']}"
                which = "best" if p["row"] == 1 else "median" if p["row"] == 2 else ""
                sub = f"{which} run · {approach_text(r.get('approach'))}" + (f" · {p['score']}" if p.get("score") else "")
                tcol = MCOL.get(model, "#272727")
            else:
                title = p["title"].split(",")[0]; sub = p.get("score") or ""; tcol = "#272727"; model = None
            key = p["key"]
            draw(ref, mov, pdir / f"{key}.png", TILE)
            draw(ref, mov, pdir / f"{key}_labelled.png", 600, title=title, sub=f"{task} · {ref_id} + {mov_id}" + (f"\n{sub}" if sub else ""), title_color=tcol)
            tiles.append(dict(key=key, kind=p["kind"], title=title, sub=sub, run_id=r["id"] if r else None, model=model))
        if not tiles: continue
        ncol = min(6, len(tiles)); nrow = -(-len(tiles) // ncol)
        sheet = Image.new("RGBA", (ncol * TILE, nrow * TILE), (0, 0, 0, 0))
        for i, t in enumerate(tiles):
            sheet.paste(Image.open(pdir / f"{t['key']}.png").convert("RGBA").resize((TILE, TILE)), ((i % ncol) * TILE, (i // ncol) * TILE)); t.update(col=i % ncol, row=i // ncol)
        sheet.save(pdir / "sprite.png", optimize=True)
        task_idx["pairs"].append(dict(name=pname, ref=ref_id, mov=mov_id, sprite=f"aligned_runs/{task}/{pname}/sprite.png", ncol=ncol, nrow=nrow, tiles=tiles))
    if task_idx["pairs"]:
        index[task] = task_idx; print(task, len(task_idx["pairs"]), "pairs", file=sys.stderr)
prev = json.loads((EX / "data" / "aligned_maps.json").read_text()) if (EX / "data" / "aligned_maps.json").exists() and ONLY else {}
prev.update(index); (EX / "data" / "aligned_maps.json").write_text(json.dumps(prev, separators=(",", ":")))
print(f"{len(index)} tasks rendered", file=sys.stderr)
