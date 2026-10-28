"""Build a self-contained copy of the explorer for hosting (no ../runs folder needed).

Traces and final-solution files go into gzip-compressed, base64-encoded JSON shards (data/tr/NN.b64.txt,
{run_id: {"trace.md": ..., "final_solution/<path>": ...}}); runs.json gets each run's shard
number in "sh". The page is written without <html>/<head>/<body> tags, for hosts that wrap it.

Usage: python explorer/pack_site.py <bundle_root> <out_dir> [--pages] [--no-traces]
  --pages      write a complete HTML document plus .nojekyll, for GitHub Pages or any static host
  --no-traces  leave out traces and final code (aggregate views only; the run view says so)
"""
import base64, gzip, json, re, shutil, sys, zlib
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve(); OUT = Path(sys.argv[2]).resolve()
PAGES = "--pages" in sys.argv; NO_TRACES = "--no-traces" in sys.argv
NSH = 64
EX = ROOT / "explorer"
# Clear the output folder but keep a .git directory, so it can be rebuilt in place inside a Pages repo.
if OUT.exists():
    for c in OUT.iterdir():
        if c.name == ".git": continue
        shutil.rmtree(c) if c.is_dir() else c.unlink()
(OUT / "data" / "tr").mkdir(parents=True, exist_ok=True); (OUT / "figures" / "out").mkdir(parents=True, exist_ok=True)

runs = json.loads((EX / "data" / "runs.json").read_text())
shards = [dict() for _ in range(NSH)]
for r in runs:
    d = ROOT / "runs" / r["id"]
    if not d.exists(): continue
    files = {}
    if (d / "trace.md").exists(): files["trace.md"] = (d / "trace.md").read_text(errors="replace")
    fin = d / "final_solution"
    if fin.exists():
        for p in sorted(fin.rglob("*")):
            if p.is_file() and p.suffix in (".py", ".R", ".sh", ".md"):
                files["final_solution/" + str(p.relative_to(fin))] = p.read_text(errors="replace")
    if files and not NO_TRACES:
        k = zlib.crc32(r["id"].encode()) % NSH
        shards[k][r["id"]] = files; r["sh"] = k
for k, sh in enumerate(shards if not NO_TRACES else []):
    # base64 of gzip, as .txt, because the host serves only plain web types
    raw = gzip.compress(json.dumps(sh, separators=(",", ":")).encode(), compresslevel=9)
    (OUT / "data" / "tr" / f"{k:02d}.b64.txt").write_text(base64.b64encode(raw).decode())
(OUT / "data" / "runs.json").write_text(json.dumps(runs, separators=(",", ":")))
for n in ("tasks.json", "taxonomy.json", "methods.json", "viewer.json"):
    if (EX / "data" / n).exists(): shutil.copy(EX / "data" / n, OUT / "data" / n)
# alignment points for the canvas viewer (explorer/build_viewer_pts.py, from the cluster export viewer_points_20261020)
if (EX / "pts").exists():
    (OUT / "pts").mkdir(exist_ok=True)
    for p in (EX / "pts").glob("*.b64.txt"): shutil.copy(p, OUT / "pts" / p.name)
for p in (EX / "figures" / "out").glob("fig*.png"): shutil.copy(p, OUT / "figures" / "out" / p.name)

html = (EX / "index.html").read_text()
title = re.search(r"<title>.*?</title>", html).group(0)
style = re.search(r"<style>.*?</style>", html, re.S).group(0)
body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
if PAGES:
    (OUT / "index.html").write_text(html); (OUT / ".nojekyll").write_text("")
else:
    (OUT / "index.html").write_text(f"{title}\n{style}\n{body}")
size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
print(f"{sum('sh' in r for r in runs)} runs packed into {NSH} shards; {size/1e6:.1f} MB total; "
      f"largest shard {max(p.stat().st_size for p in (OUT/'data'/'tr').iterdir())/1e6:.2f} MB")
