"""Tag every run in the agent strategies bundle with phases and method keywords.

Reads runs/<run_id>/{meta.json,steps.json,final_solution/} and scores/*.csv and writes
explorer/data/{runs.json,tasks.json,taxonomy.json}, which explorer/index.html loads.

Usage (from anywhere):
    python explorer/tag_runs.py <bundle_root>

Each tool call gets one phase letter (see PHASES). Running a script inherits the phase
of the step that wrote it, as in RCT_Bench agentbench/scripts/extract_trace_features.py.
Keywords are regexes over code (commands, written file contents, edits) and, separately,
over the agent's own narration. Codex apply_patch events carry no file contents, so for
Codex the code signal only sees shell commands, inline code and the final snapshot.
"""
import ast, csv, json, math, re, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OUT = ROOT / "explorer" / "data"

# ---------------- keyword taxonomy, grouped by pipeline stage ----------------
STAGES = [
    ("prep", "Preprocessing / features"),
    ("init", "Coarse initialization"),
    ("match", "Correspondence / fitting"),
    ("model", "Transform model"),
    ("pkg", "Published method"),
    ("multi", "Multi-slice strategy"),
    ("check", "Self-evaluation / selection"),
]
def CS(p): return "(?-i:" + p + ")"  # case-sensitive pattern
KW = [
    # stage, key, label, pattern, definition
    ("prep", "gene_intersect", "Shared-gene intersection", r"set\([^()\n]*\)\s*&\s*set\(|intersect1d|common_genes|shared_genes|genes_common|var_names\.intersection|\.intersection\(", "Restrict both slices to genes measured in both before comparing expression."),
    ("prep", "normalize", "Normalize / log1p", r"log1p|normalize_total|\bcp10k\b|\bcpm\b", "Library-size normalization and log transform of counts."),
    ("prep", "hvg", "Highly variable genes", r"highly_variable|\bhvgs?\b|top_var", "Keep only the most variable genes."),
    ("prep", "pca", "PCA / SVD embedding", r"\bPCA\(|TruncatedSVD|linalg\.svd\(|randomized_svd|pp\.pca\(|\btl\.pca\(", "Low-dimensional expression embedding shared by the slices."),
    ("prep", "integration", "Batch integration", r"harmony|scanorama|\bcombat\b|bbknn|\bscvi\b|\bCCA\(", "Remove platform or batch differences before matching (Harmony, Scanorama, ComBat, CCA, scVI)."),
    ("prep", "cluster", "Clustering / domains", r"KMeans|leiden|louvain|GaussianMixture|AgglomerativeClustering|SpectralClustering", "Cluster cells or spots into types or spatial domains and match on labels."),
    ("init", "centroid", "Centroid centering", r"centroid|cent(er|re)ing", "Translate each slice so its centroid sits at the origin."),
    ("init", "flip", "Flip / mirror search", r"flip|mirror|reflect", "Consider reflected orientations, not only rotations."),
    ("init", "rot_grid", "Rotation grid search", r"for\s+\w*(ang|theta|rot|deg)\w*\s+in\b|(arange|linspace)\([^)\n]{0,30}360|range\(\s*0\s*,\s*360", "Score a grid of rotation angles and keep the best."),
    ("init", "principal_axes", "Principal-axis alignment", r"principal.?ax|eigh\(\s*np\.cov|np\.cov\([^)\n]*(xy|coord|pts|points)", "Align the slices' principal axes (second moments) to fix rotation."),
    ("init", "raster", "Rasterize to image", r"histogram2d|rasteri[sz]|to_image\(|np\.add\.at\(|binned_image|density_image|grid_image", "Bin cells or spots into a density or expression image."),
    ("init", "xcorr", "FFT / cross-correlation", r"fftconvolve|correlate2d|phase_cross_correlation|cross.?correl|np\.fft|scipy\.fft|match_?template|matchTemplate", "Find the shift (and angle) that maximizes image correlation."),
    ("match", "knn", "Nearest-neighbor search", r"NearestNeighbors|cKDTree|KDTree|kneighbors|BallTree", "kNN or KD-tree queries, in space or in expression."),
    ("match", "mnn", "Mutual nearest neighbors", r"mutual|\bmnn\b", "Keep only cross-slice pairs that are each other's nearest neighbor."),
    ("match", "hungarian", "Hungarian assignment", r"linear_sum_assignment", "One-to-one assignment between cells or clusters."),
    ("match", "ot", "Optimal transport", r"\bot\.(emd|sinkhorn|gromov|unbalanced|dist)|import ot\b|optimal.transport|sinkhorn|gromov", "Soft matching by optimal transport (POT, Sinkhorn, fused Gromov-Wasserstein)."),
    ("match", "ransac", "RANSAC", r"ransac", "Robust transform fitting from noisy correspondences."),
    ("match", "procrustes", "Procrustes / Kabsch / Umeyama", r"procrustes|kabsch|umeyama", "Closed-form best rotation (and scale) from matched point pairs."),
    ("match", "icp", "ICP", r"\bicp\b|iterative.closest", "Iterative closest point: alternate nearest-neighbor matching and Procrustes."),
    ("match", "cpd", "Coherent point drift", r"\bcpd\b|coherent.point|pycpd|probreg", "Probabilistic point-set registration."),
    ("match", "optimizer", "Numerical optimizer", r"minimize\(|least_squares\(|differential_evolution\(|basinhopping\(|dual_annealing\(|minimize_scalar\(", "Generic scipy optimizer over transform parameters."),
    ("match", "gradient", "Gradient / autograd", r"\btorch\b|autograd|\bjax\b", "Fit by gradient descent in PyTorch or JAX."),
    ("model", "rigid", "Rigid", r"\brigid|EuclideanTransform|\bcos\(|rotation_?matri|rot_?mat|\bRmat\b|Rotation\.from", "Rotation plus translation (including hand-built rotation matrices)."),
    ("model", "similarity", "Similarity (with scale)", r"similarity.?(transform|align)|SimilarityTransform|with_scaling\s*=\s*True|umeyama|isotropic.?scal", "Rigid plus a single scale factor."),
    ("model", "affine", "Affine", r"\baffine|AffineTransform", "General linear map plus translation (shear, anisotropic scale)."),
    ("model", "nonrigid", "Non-rigid / deformable", r"thin.?plate|\btps\b|RBFInterpolator|\bRbf\(|non.?rigid|deformable|b.?spline|displacement.?field|lddmm|diffeomorph|piecewise.?affine", "Local deformation: TPS, RBF, B-spline, displacement field, LDDMM."),
    ("pkg", "PASTE", "PASTE", CS(r"import paste\b|from paste\b|\bpst\.|pairwise_align\(|center_align\(|\bPASTE\b(?!2)"), "Optimal-transport alignment of adjacent slices (Zeira et al. 2022)."),
    ("pkg", "PASTE2", "PASTE2", r"paste2|partial_pairwise_align", "Partial optimal-transport extension of PASTE."),
    ("pkg", "SPACEL", "SPACEL", r"spacel|scube|splane", "SPACEL Scube 3D alignment / Splane domains."),
    ("pkg", "spateo", "Spateo", r"spateo|morpho_align", "Spateo morpho_align (rigid + non-rigid)."),
    ("pkg", "CAST", "CAST", CS(r"\bCAST\b|CAST_MARK|CAST_STACK|from CAST|import CAST"), "CAST graph-embedding alignment."),
    ("pkg", "STalign", "STalign", r"stalign", "Image-based LDDMM alignment."),
    ("pkg", "moscot", "moscot", r"moscot", "moscot optimal-transport alignment."),
    ("pkg", "GPSA", "GPSA", r"\bgpsa\b", "Gaussian-process spatial alignment."),
    ("pkg", "SLAT", "SLAT", CS(r"\bSLAT\b|scSLAT|run_SLAT"), "SLAT graph-matching alignment."),
    ("pkg", "STAligner", "STAligner", r"staligner", "STAligner embedding + ICP."),
    ("pkg", "GEASO", "GEASO", r"geaso", "GEASO (Wang, Liu & Ma 2026)."),
    ("pkg", "SANTO", "SANTO", CS(r"\bSANTO\b|import santo|from santo"), "SANTO coarse-to-fine alignment."),
    ("pkg", "STAIR", "STAIR", CS(r"\bSTAIR\b|import stair|from stair"), "STAIR alignment."),
    ("multi", "sequential", "Sequential chaining", r"sequential|chain(ed|ing)?\b|cumulative|consecutive|adjacent.pair|compose", "Align each slice to its neighbor and compose the transforms."),
    ("multi", "reference", "Common reference slice", r"reference.?slice|ref_slice|\bref_idx|center_align|anchor.?slice", "Align every slice to one reference or center slice."),
    ("multi", "stitch", "Stitching / overlap", r"stitch|overlap.?(region|area|fraction)", "Stitch tiles using their overlapping area."),
    ("multi", "z_stack", "3D stacking", r"\bz_?coord|z_spacing|3d.?(stack|reconstruct)", "Treat slices as a 3D stack."),
    ("check", "proxy_metric", "Internal alignment score", r"def (evaluate|score|objective)\w*\(|(neighbo.?r|knn)\w{0,3}_?(agree|consist|purity|corr)|alignment.?(score|quality|metric)|chamfer|hausdorff|overlap.?(ratio|iou|score)|\biou\b|expr\w*_?(corr|similarity|agreement)", "A label-free score the agent computes to judge an alignment (neighbor expression agreement, overlap, Chamfer distance)."),
    ("check", "synthetic", "Synthetic transform test", r"synthetic|known.?(rotation|transform|shift)|random.?(rotation|transform)|recover(ed|s)?\s+(the\s+)?(rotation|transform|angle)", "Apply a known transform to the data and check that the method recovers it."),
    ("check", "visual", "Plot for visual QC", r"savefig|imshow\(|plt\.scatter|ax\.scatter", "Render the aligned slices to an image."),
    ("check", "looked_at_plot", "Looked at a plot", None, "The agent opened an image file it made (Read / read_file on a .png)."),
    ("check", "web", "Web search", None, "The agent ran a web search."),
]
# Middle level of the strategy tables (stage > category > keyword), as in the Genomics agent notes.
CATEGORY = {
    "gene_intersect": "Gene handling", "normalize": "Expression scale", "hvg": "Expression scale",
    "pca": "Embedding", "integration": "Embedding", "cluster": "Cell labels",
    "centroid": "Centering", "flip": "Orientation search", "rot_grid": "Orientation search", "principal_axes": "Orientation search",
    "raster": "Image-based registration", "xcorr": "Image-based registration",
    "knn": "Point correspondence", "mnn": "Point correspondence", "hungarian": "Point correspondence", "ot": "Point correspondence",
    "ransac": "Transform estimation", "procrustes": "Transform estimation", "icp": "Transform estimation", "cpd": "Transform estimation",
    "optimizer": "Parameter search", "gradient": "Parameter search",
    "rigid": "Transform family", "similarity": "Transform family", "affine": "Transform family", "nonrigid": "Transform family",
    "PASTE": "Optimal-transport methods", "PASTE2": "Optimal-transport methods", "moscot": "Optimal-transport methods", "spateo": "Optimal-transport methods",
    "SPACEL": "Embedding / graph methods", "CAST": "Embedding / graph methods", "SLAT": "Embedding / graph methods", "STAligner": "Embedding / graph methods",
    "STAIR": "Embedding / graph methods", "GEASO": "Embedding / graph methods", "SANTO": "Embedding / graph methods",
    "STalign": "Image-based methods", "GPSA": "Image-based methods",
    "sequential": "Slice ordering", "reference": "Slice ordering", "stitch": "Tiling / 3D", "z_stack": "Tiling / 3D",
    "proxy_metric": "Label-free validation", "synthetic": "Label-free validation", "visual": "Visual check", "looked_at_plot": "Visual check",
    "web": "Outside info",
}
KW_RE = {k: re.compile(p, re.I | re.M) for _, k, _, p, _ in KW if p}
KW_STAGE = {k: s for s, k, _, _, _ in KW}
PKGS = [k for s, k, *_ in KW if s == "pkg"]
TRANSFORM_ORDER = ["nonrigid", "affine", "similarity", "rigid"]

# ---------------- phases ----------------
PHASES = [
    ("L", "inspect data / task"),
    ("S", "set up env / read package docs"),
    ("P", "preprocess / features"),
    ("A", "try an alignment method"),
    ("E", "evaluate / compare candidates"),
    ("W", "write the submission"),
    ("V", "validate output / report"),
    ("O", "wait / housekeeping"),
]
LOOK = re.compile(r"^\s*(cd [^;&\n]+[;&]+\s*)?(ls|find|cat|head|tail|sed -n|nl|wc|grep|rg|tree|du|df|nvidia-smi|nproc|free|file|stat)\b|TASK\.md|h5py|\.keys\(\)|\.shape\b|obsm|read_h5ad|describe\(|dtype|list_directory|glob|grep_search|\"file_path\"", re.I | re.M)
SETUP = re.compile(r"pip (install|list|show)|uv (pip|venv|run --with)|conda |\.method-(cache|venv)|site-packages|help\(|inspect\.getsource|__doc__|README|import(lib)?\.metadata|--version|which python", re.I)
WAIT = re.compile(r"^\s*(cd [^;&\n]+[;&]+\s*)?(sleep|until|while|ps |pgrep|kill|tail -f|wait\b)|/agent-state/tmp/", re.I | re.M)
VALID = re.compile(r"report\.json|aligned_coordinates[^\n]*(wc|head|read_csv|shape|len\(|nunique|isna|isnull|duplicated|assert)|(wc|head|read_csv|assert)[^\n]*aligned_coordinates|verify_submission|validate", re.I)
CHECK_KEYS = ["proxy_metric", "synthetic", "visual"]
METHOD_STAGES = ("init", "match", "model", "pkg")
CODE = re.compile(r"python|agent_python|<<|Rscript|\.py\b|\.R\b", re.I)
SCRIPT_RUN = re.compile(r"(?:python3?|agent_python\.sh|uv run(?: python)?|Rscript|bash|sh)\s+(?:-u\s+)?['\"]?([\w./-]+\.(?:py|R|sh))")
TRANSITION = re.compile(r"\b(switch(ing)?|instead|revert|fall ?back|abandon|worse|better than|outperform|beats?|improv(es|ed)|keep(ing)? the|go(ing)? with|stick with|final(ize|izing)? (with|on)|chose|choose)\b", re.I)

def hits(text, stages=None):
    return {k for k, r in KW_RE.items() if (stages is None or KW_STAGE[k] in stages) and r.search(text)}

def phase_of(step, text, out, kw):
    name = (step.get("name") or "").lower()
    if step.get("writes_submission"): return "W"
    path = step.get("path") or ""
    if "report.json" in path or VALID.search(text): return "V"
    if name in ("web_search", "google_web_search"): return "S"
    if name in ("read", "read_file") and re.search(r"\.(png|jpe?g|svg)\b", text, re.I): return "E"
    if name in ("monitor", "taskstop", "schedulewakeup", "read_background_output", "list_background_processes", "toolsearch", "update_topic", "enter_plan_mode", "exit_plan_mode"): return "O"
    if kw & set(CHECK_KEYS): return "E"
    if kw & {k for k in kw if KW_STAGE[k] in METHOD_STAGES}: return "A"
    if kw & {k for k in kw if KW_STAGE[k] == "prep"}: return "P"
    if SETUP.search(text): return "S"
    if WAIT.search(text): return "O"
    if LOOK.search(text) or name in ("read", "read_file", "list_directory", "glob", "grep_search"): return "L"
    return "O"

def ts(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

def fnum(x):
    try: return float(x) if x not in ("", None) else None
    except ValueError: return None

def short(s, n=280):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def analyse(run_dir, meta):
    steps = json.loads((run_dir / "steps.json").read_text())
    fin_dir = run_dir / "final_solution"
    fin_paths = sorted(p for p in fin_dir.rglob("*") if p.is_file() and p.suffix in (".py", ".R", ".sh")) if fin_dir.exists() else []
    fin_files = {p.name: p.read_text(errors="ignore") for p in fin_paths}
    final_code = "\n".join(fin_files.values())
    written_phase, written_kw = {}, {}
    seq, seq_n, kw_first, kw_text, stepdur = [], [], {}, set(), Counter()
    pkg_order, quotes = [], []
    tool_idx = 0
    times = [ts(s["ts"]) if s.get("ts") else None for s in steps]
    for i, s in enumerate(steps):
        if s["kind"] in ("text", "thinking"):
            t = s.get("text") or ""
            kw_text |= hits(t)
            for sent in re.split(r"(?<=[.!?])\s+", t):
                if 40 < len(sent) < 400 and TRANSITION.search(sent) and len(quotes) < 6:
                    quotes.append(short(sent, 300))
            continue
        if s["kind"] != "tool": continue
        cmd = s.get("command") or ""; content = s.get("content") or ""; path = s.get("path") or ""
        text = cmd + "\n" + content
        name = (s.get("name") or "").lower()
        # Codex patches carry no content: fall back to the final snapshot of that file if present.
        if name == "apply_patch" and path and Path(path).name in fin_files:
            text += "\n" + fin_files[Path(path).name]
        # Plain shell inspection (ls, grep, cat of a package's source) does not count as trying a method.
        is_code = bool(content) or name == "apply_patch" or bool(CODE.search(cmd))
        kw = hits(text) if is_code else set()
        if name in ("web_search", "google_web_search"): kw.add("web")
        if name in ("read", "read_file") and re.search(r"\.(png|jpe?g)\b", cmd, re.I): kw.add("looked_at_plot")
        ph = phase_of(s, text, s.get("output") or "", kw)
        is_write = name in ("write", "write_file", "edit", "replace", "apply_patch") and path
        if is_write:
            written_phase[Path(path).name] = ph if ph not in ("L", "O") else written_phase.get(Path(path).name, ph)
            written_kw[Path(path).name] = kw
        ran = s.get("ran_scripts") or []
        if isinstance(ran, str):
            try: ran = ast.literal_eval(ran) if ran.startswith("[") else [ran]
            except Exception: ran = []
        if not is_write:
            for m in SCRIPT_RUN.finditer(cmd): ran = list(ran) + [m.group(1)]
            for r in ran:
                b = Path(r).name
                if b in written_kw: kw |= written_kw[b]
                elif b in fin_files: kw |= hits(fin_files[b])
                if ph in ("L", "O", "S") and b in written_phase and written_phase[b] not in ("L", "O"):
                    ph = written_phase[b]
            if ph in ("L", "O") and ran:
                ph = phase_of(s, text, "", kw) if kw else ph
        tool_idx += 1
        for k in kw:
            kw_first.setdefault(k, tool_idx)
            if KW_STAGE[k] == "pkg" and k not in pkg_order and not is_write: pkg_order.append(k)
        err = s.get("ok") is False
        seq.append(ph.lower() if err else ph); seq_n.append(s["n"])
        # time attributed to this step = until the next event with a timestamp
        if times[i] is not None:
            nxt = next((t for t in times[i + 1:] if t is not None), None)
            if nxt is not None: stepdur[ph] += max(0.0, nxt - times[i])
    kw_final = hits(final_code) if final_code else set()
    pkg_final = [p for p in PKGS if p in kw_final]
    transform = next((t for t in TRANSFORM_ORDER if t in kw_final), "unlabelled" if final_code else "no code found")
    # what the submission "is": a published package if its code calls one, else a custom transform family
    approach = ("pkg:" + pkg_final[0]) if pkg_final else ("custom:" + transform if final_code else "no code found")
    n_final_lines = sum(1 for l in final_code.splitlines() if l.strip() and not l.strip().startswith("#"))
    return dict(seq="".join(seq), seq_n=seq_n, dur={k: round(v, 1) for k, v in stepdur.items()},
                kw_code=kw_first, kw_text=sorted(kw_text), kw_final=sorted(kw_final),
                pkg_order=pkg_order, pkg_final=pkg_final, transform=transform, approach=approach,
                n_final_lines=n_final_lines, final_files=[str(p.relative_to(fin_dir)) for p in fin_paths], quotes=quotes)

def main():
    scores = {r["run_id"]: r for r in csv.DictReader(open(ROOT / "scores" / "agent_scores.csv"))}
    runs = []
    dirs = sorted(p for p in (ROOT / "runs").iterdir() if (p / "meta.json").exists())
    for n, d in enumerate(dirs):
        meta = json.loads((d / "meta.json").read_text())
        sc = scores.get(meta["run_id"], {})
        ex = meta.get("exploration") or {}
        fs = meta.get("final_solution") or {}
        r = dict(id=meta["run_id"], agent=meta["agent"], model=meta["model"], effort=meta.get("reasoning_effort"),
                 cond=meta["condition"], task=meta["task"], family=meta["family"], dataset=meta.get("dataset"),
                 status=meta["status"], leak=meta.get("leakage_status"), fail_stage=meta.get("failure_stage"), fail_msg=short(meta.get("failure_message"), 200),
                 score=fnum(sc.get("score_overall_mean", meta.get("score_overall_mean"))) if meta["status"] == "scored" else None,
                 acc=fnum(sc.get("score_matching_accuracy")), maered=fnum(sc.get("score_mae_reduction")),
                 pcc=fnum(sc.get("score_gene_pcc")), ssim=fnum(sc.get("score_gene_ssim")),
                 mae=fnum(sc.get("score_mae")) if meta["status"] == "scored" else None,
                 wall=ex.get("wall_s"), cost=ex.get("cost_usd"), out_tok=ex.get("output_tokens"),
                 n_tool=ex.get("n_tool_calls"), n_err=ex.get("n_tool_errors"), n_scripts=ex.get("n_scripts_written"),
                 n_subw=ex.get("n_submission_writes"), t_first=ex.get("t_first_submission_s"),
                 t_first_how=ex.get("t_first_submission_method"), n_web=ex.get("n_web_search"),
                 entry=fs.get("entry"), how=fs.get("how"), final_step=fs.get("step"), started=meta.get("started_at"))
        if meta["status"] != "no_manifest" and (d / "steps.json").exists():
            try: r.update(analyse(d, meta))
            except json.JSONDecodeError: r["parse_error"] = True
        runs.append(r)
        if n % 500 == 0: print(f"{n}/{len(dirs)}", file=sys.stderr)

    # runs that never wrote a manifest have no folder, only a row in agent_scores.csv
    have = {r["id"] for r in runs}
    for rid, sc in scores.items():
        if rid in have: continue
        runs.append(dict(id=rid, agent=sc["agent"], model=sc["model"], effort=sc.get("reasoning_effort") or None,
                         cond=sc["condition"], task=sc["task"], family=sc["family"], dataset=sc.get("dataset") or None,
                         status=sc["status"] or "unknown", fail_stage=sc.get("failure_stage") or None, fail_msg=None,
                         score=None, no_folder=True))

    # within-task percentile of the overall score among scored agent runs (0 = worst, 1 = best)
    by_task = defaultdict(list)
    for r in runs:
        if r["status"] == "scored" and r["score"] is not None: by_task[r["task"]].append(r)
    for t, rs in by_task.items():
        vals = sorted(x["score"] for x in rs)
        for x in rs:
            lo = sum(v < x["score"] for v in vals); eq = sum(v == x["score"] for v in vals)
            x["pct"] = round((lo + (eq - 1) / 2) / max(1, len(vals) - 1), 4)

    # MAE exists only for tasks with true coordinates; percentile among scored runs with an MAE, 100 = lowest MAE
    mae_task = defaultdict(list)
    for r in runs:
        if r["status"] == "scored" and r.get("mae") is not None: mae_task[r["task"]].append(r)
    for t, rs in mae_task.items():
        vals = sorted(x["mae"] for x in rs)
        for x in rs:
            lo = sum(v < x["mae"] for v in vals); eq = sum(v == x["mae"] for v in vals)
            x["mae_pct"] = round(1 - (lo + (eq - 1) / 2) / max(1, len(vals) - 1), 4)

    # baselines: best variant per method per task
    # Published methods and naive fits only. The strategy-synthesis policies (synth_*) are kept apart in synth/synth_mae,
    # and the SPACEL variants that read the true labels (*truelabels*) are dropped, so neither can be the best published.
    base = defaultdict(dict); base_mae = defaultdict(dict); synth = defaultdict(dict); synth_mae = defaultdict(dict)
    for b in csv.DictReader(open(ROOT / "scores" / "baseline_scores.csv")):
        v = fnum(b["score_overall_mean"])
        if v is None or b["method"] == "method": continue
        if "truelabels" in (b.get("variant") or ""): continue
        if b["method"].startswith("synth_"):
            synth[b["task"]][b["method"]] = round(v, 4)
            mv = fnum(b.get("score_mae"))
            if mv is not None: synth_mae[b["task"]][b["method"]] = round(mv, 3)
            continue
        cur = base[b["task"]].get(b["method"])
        if cur is None or v > cur["score"]: base[b["task"]][b["method"]] = dict(score=round(v, 4), variant=b["variant"])
        mv = fnum(b.get("score_mae"))
        if mv is not None:
            cm = base_mae[b["task"]].get(b["method"])
            if cm is None or mv < cm: base_mae[b["task"]][b["method"]] = round(mv, 3)
    naive = {"identity", "centroid_similarity", "icp_similarity", "pca_similarity"}
    tasks = {}
    for t in sorted({r["task"] for r in runs}):
        bm = base.get(t, {})
        pub = {m: v for m, v in bm.items() if m not in naive}
        best_pub = max(pub.items(), key=lambda kv: kv[1]["score"]) if pub else None
        best_naive = max(((m, v) for m, v in bm.items() if m in naive), key=lambda kv: kv[1]["score"], default=None)
        tasks[t] = dict(family=next(r["family"] for r in runs if r["task"] == t),
                        dataset=next((r["dataset"] for r in runs if r["task"] == t and r["dataset"]), None),
                        baselines=bm, best_pub=best_pub, best_naive=best_naive,
                        baselines_mae=base_mae.get(t, {}),
                        best_pub_mae=min(((m, v) for m, v in base_mae.get(t, {}).items() if m not in naive), key=lambda kv: kv[1], default=None),
                        best_naive_mae=min(((m, v) for m, v in base_mae.get(t, {}).items() if m in naive), key=lambda kv: kv[1], default=None),
                        synth=synth.get(t, {}), synth_mae=synth_mae.get(t, {}),
                        n_scored=len(by_task.get(t, [])))
    for r in runs:
        tb = tasks[r["task"]]
        if r.get("score") is not None:
            r["vs_pub"] = round(r["score"] - tb["best_pub"][1]["score"], 4) if tb["best_pub"] else None
            r["vs_naive"] = round(r["score"] - tb["best_naive"][1]["score"], 4) if tb["best_naive"] else None
        if r.get("mae") is not None:
            # MAE gain over a baseline = log2(baseline MAE / run MAE): positive = lower error, +1 = half the error (capped at +-6)
            for key, ref in (("mae_gain_pub", tb["best_pub_mae"]), ("mae_gain_naive", tb["best_naive_mae"])):
                if ref and ref[1] > 0: r[key] = round(max(-6, min(6, math.log2(ref[1] / max(r["mae"], ref[1] / 64)))), 4)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs.json").write_text(json.dumps(runs, separators=(",", ":")))
    (OUT / "tasks.json").write_text(json.dumps(tasks, separators=(",", ":")))
    (OUT / "taxonomy.json").write_text(json.dumps(dict(
        stages=[dict(key=k, label=l) for k, l in STAGES],
        keywords=[dict(stage=s, category=CATEGORY.get(k, ""), key=k, label=l, pattern=p, definition=d) for s, k, l, p, d in KW],
        phases=[dict(key=k, label=l) for k, l in PHASES]), indent=1))
    print(f"wrote {len(runs)} runs, {len(tasks)} tasks to {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
