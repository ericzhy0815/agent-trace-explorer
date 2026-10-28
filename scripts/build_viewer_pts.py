"""Convert the cluster viewer export (viewer_points_20261020) into compact per-task files for the explorer.

Per task, one file pts/<task>.b64.txt = base64(gzip(binary)), and one index data/viewer.json with every task's
metadata (panels, scores, labels, caveats, byte offsets). The host serves only plain web types, hence base64 text.

Binary layout per view (pair01..03, stack), bytes only:
  sec  uint8[n]           pairs: 0 = reference, 1 = moving; stacks: section index
  lab  uint8[n]           label code (255 = none)
  xy   uint8[P, n, 3]     per panel, x and y quantized to 12 bits in the panel's bounding box and packed into 3 bytes
                          (x >> 4, (x & 15) << 4 | y >> 8, y & 255); 4095, 4095 = missing
Cells are a further fixed subsample of the export's cells (same cells for every panel).

Usage: vpenv/bin/python -I build_viewer_pts.py <viewer_points_dir> <explorer_site_dir>
"""
import base64, gzip, json, os, sys
import numpy as np, pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
CAP_PAIR, CAP_STACK_SEC, CAP_STACK_TOT = 1000, 150, 8000
NAMES = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "gpt-6-astra": "GPT-6 Astra", "gpt-5.5": "GPT-5.5",
         "gemini-4-argon": "Gemini 4 Argon", "gemini-3.5-flash": "Gemini 3.5 Flash"}
SKEYS = ["overall_mean", "mae", "ex", "matching_accuracy", "mnn_label_accuracy", "mnn_expression_cosine"]
DLPFC_PERTURB = {"sa-002", "sa-003", "sa-040", "sa-041"}

os.makedirs(os.path.join(OUT, "pts"), exist_ok=True)
index, total, fails = {}, 0, []


def r4(v):
    return None if v is None or not np.isfinite(v) else float(f"{v:.4g}")


def pick(groups, cap, seed):
    """Fixed subsample: up to cap cells from each group (rows of the export), in original order."""
    rng = np.random.default_rng(seed); keep = []
    for g in np.unique(groups):
        ix = np.flatnonzero(groups == g)
        keep.append(ix if len(ix) <= cap else np.sort(rng.choice(ix, cap, replace=False)))
    return np.sort(np.concatenate(keep))


def caveats(t, m):
    c, short = [], t[:6]
    if short == "sa-019": c.append("Truth panel is in units 20 times smaller than the input (the scorer's truth and the published Flysta3D MAE share this mismatch), so input and truth differ in scale.")
    if short == "sa-406": c.append("No published method produced results on this task.")
    if short in DLPFC_PERTURB: c.append("Truth panel: the original Visium position of each spot, rigidly mapped onto the reference input. The task scorer reports no MAE here; panels are ranked by overall score.")
    if short == "sa-410": c.append("The best SPACEL panel here is the variant that reads the true labels.")
    if short == "sa-023": c.append("The unaligned input is already within about 1 µm of the truth (truth = reference input shifted by a constant).")
    if short in ("sa-414", "sa-415", "sa-416", "sa-417"): c.append("Truth is the authors' registered (CCF-based) frame; no section's raw input is in it, so the input panel is not in the truth frame.")
    if str(m.get("units", "")).endswith("*"): c.append(f"Units ({m['units'].rstrip('*')}) are inferred: {m.get('units_basis', '')}.")
    return c


for t in sorted(os.listdir(SRC)):
    d = os.path.join(SRC, t)
    if not os.path.isdir(d): continue
    m = json.load(open(os.path.join(d, "manifest.json")))
    keep_p = [i for i, p in enumerate(m["panels"]) if p["kind"] != "program"]
    panels = []
    for i in keep_p:
        p = m["panels"][i]
        q = {"id": p["id"], "kind": p["kind"]}
        if p["kind"] == "published": q.update(name=p["method"], variant=p.get("variant"), best=bool(p.get("best")))
        elif p["kind"] == "naive": q.update(name="Naive: " + str(p.get("variant", "")).replace("_", " "))
        elif p["kind"] == "agent": q.update(model=p["model"], cond=p["condition"], run_id=p.get("run_id"),
                                            name=f"{NAMES.get(p['model'], p['model'])} · {'basic' if p['condition'] == 'bare' else 'rich'}")
        elif p["kind"] == "truth": q.update(name="Truth")
        elif p["kind"] == "input": q.update(name="Input")
        if p.get("missing"): q["missing"] = True
        s = m["scores"].get(p["id"]) or {}
        sc = {k: r4(s.get(k)) for k in SKEYS if s.get(k) is not None}
        if sc: q["s"] = sc
        panels.append(q)
    views, blobs, off = [], [], 0
    for v in [p["id"] for p in m["pairs"]] + (["stack"] if m.get("stack") else []):
        try:
            cells = pd.read_parquet(os.path.join(d, f"{v}_cells.parquet"))
            xy = np.load(os.path.join(d, f"{v}_xy.npy"))[keep_p]
        except Exception as e:
            fails.append(f"{t}/{v}: {e}"); continue
        if v == "stack":
            g = cells["section_index"].to_numpy()
            ns = len(np.unique(g)); cap = max(20, min(CAP_STACK_SEC, CAP_STACK_TOT // ns))
            sec = g.astype(np.uint8)
        else:
            g = (cells["section"].to_numpy() == "mov").astype(int); cap = CAP_PAIR; sec = g.astype(np.uint8)
        ix = pick(g, cap, [20261021, len(views)])
        lab = cells["label_code"].to_numpy()[ix]; lab = np.where((lab < 0) | (lab > 254), 255, lab).astype(np.uint8)
        sec, xy = sec[ix], xy[:, ix, :]
        bbox, q16 = [], np.full(xy.shape, 4095, np.uint16)
        for k in range(xy.shape[0]):
            a = xy[k]; ok = np.isfinite(a).all(1)
            if not ok.any(): bbox.append(None); continue
            lo, hi = a[ok].min(0), a[ok].max(0); span = np.maximum(hi - lo, 1e-9)
            q16[k, ok] = np.round((a[ok] - lo) / span * 4094).astype(np.uint16)
            bbox.append([float(lo[0]), float(lo[1]), float(span[0]), float(span[1])])
        x, y = q16[..., 0].astype(np.uint16), q16[..., 1].astype(np.uint16)
        pk = np.stack([(x >> 4), ((x & 15) << 4) | (y >> 8), (y & 255)], -1).astype(np.uint8)
        b = sec.tobytes() + lab.tobytes() + pk.tobytes()
        meta = {"id": v, "n": int(len(ix)), "off": off, "bbox": bbox}
        if v == "stack": meta["n_sections"] = int(m["stack"]["n_sections"]); meta["per_section"] = int(cap)
        else:
            pr = next(p for p in m["pairs"] if p["id"] == v); meta.update(ref=pr["ref"], mov=pr["mov"])
        views.append(meta); blobs.append(b); off += len(b)
    if not views: fails.append(f"{t}: no views"); continue
    raw = gzip.compress(b"".join(blobs), compresslevel=9)
    txt = base64.b64encode(raw)
    open(os.path.join(OUT, "pts", f"{t}.b64.txt"), "wb").write(txt); total += len(txt)
    index[t] = {"units": m.get("units"), "frame": m.get("frame"), "truth": bool(m.get("truth")), "labels": bool(m.get("labels")),
                "metric": m.get("primary_metric"), "n_sections": m.get("n_sections"),
                "labels_table": [[l["code"], l["name"]] for l in (m.get("labels_table") or [])][:40],
                "panels": panels, "views": views, "caveats": caveats(t, m), "bytes": off}
json.dump(index, open(os.path.join(OUT, "data", "viewer.json"), "w"), separators=(",", ":"))
print(f"{len(index)} tasks; points {total/1e6:.1f} MB as base64; index {os.path.getsize(os.path.join(OUT, 'data', 'viewer.json'))/1e6:.2f} MB; "
      f"largest {max(os.path.getsize(os.path.join(OUT, 'pts', f)) for f in os.listdir(os.path.join(OUT, 'pts')))/1e6:.2f} MB")
for f in fails: print("FAIL", f)
