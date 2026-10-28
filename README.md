# Agent Trace Explorer — Self-Contained Website Bundle

This repository is a complete, static, zero-backend website for the **Spatial Alignment Agent Trace Explorer** (2026-10-23 analysis set: 121 tasks × 6 models × 2 conditions = 1,452 runs, plus 4,414 published/baseline configurations and interactive 2D/3D coordinate point-cloud viewers).

**Live site:** https://ericzhy0815.github.io/agent-trace-explorer/

## Quick Local Preview

From inside this directory, run any static HTTP server:

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

Then open <http://127.0.0.1:8765/> in your browser.

## How to Host

Because every asset is a plain static file (`.html`, `.json`, `.png`, `.txt`) and decompression happens in the browser via `DecompressionStream("gzip")`, **no backend, database, or custom MIME/encoding headers are needed**:

1. **GitHub Pages / Cloudflare Pages / Netlify / Vercel / S3**:
   - Serve this directory as the site root (`index.html` is a full HTML5 document, and `.nojekyll` is included so GitHub Pages does not ignore underscore files).
2. **Artifact / Wrapper Hosts (e.g., Claude Artifacts)**:
   - If the host wraps the page in its own `<html>/<head>/<body>` shell, use `index_artifact.html` as the entry HTML instead of `index.html`.

## Directory Layout

- `index.html` — Standalone single-page app (`<!doctype html>…</html>`) for standard static hosting.
- `index_artifact.html` — Fragment version (without outer `<html>/<head>/<body>` tags) for wrapper hosts.
- `.nojekyll` — Disables Jekyll processing on GitHub Pages.
- `data/`
  - `runs.json` — Metadata, scores, within-task percentiles, phase strips, keywords, and shard IDs (`sh: 0..64`) for all 1,452 analysis-set runs.
  - `tasks.json` — Per-task metadata and best published/naive/synthesized baseline summaries across all 121 tasks.
  - `taxonomy.json` — Pipeline stages, method keyword regex definitions, and agent execution phases.
  - `methods.json` — Full configuration-level benchmark table (4,414 baseline configurations + 1,452 agent runs) for the **Published methods** tab.
  - `viewer.json` — Panel metadata, cell-type/region label tables, bounding boxes, and scores (27 panels per task) for the **Alignments** tab.
  - `tr/00.b64.txt` … `64.b64.txt` — 65 gzip-compressed, base64-encoded JSON shards containing full execution logs (`trace.md`) and submitted code (`final_solution/*`) for all 1,452 runs.
  - *(Optional `--no-traces` hosting)*: If you ever need a lightweight (~40 MB) deployment without individual run traces, you can omit `data/tr/`; all aggregate tabs, heatmaps, and the interactive alignment viewer will still work.
- `pts/*.b64.txt` — 121 gzip-compressed, base64-encoded binary point-cloud files (12-bit quantized 2D pair & 3D stack coordinates) rendered on HTML5 `<canvas>` in the **Alignments** tab.
- `figures/out/fig1_overview.png` … `fig7_selection.png` — Manuscript main figures (`#figures`).
- `scripts/` — The Python scripts used to build and pack this site from the raw evaluation bundle (`tag_runs.py`, `pack_site.py`, `filter_analysis_set.py`, `build_methods_json.py`, `build_viewer_pts.py`).
