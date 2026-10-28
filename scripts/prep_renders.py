"""Rasterize the aligned-result PDFs of the 20261020 bundle into JPGs for the explorer.

Writes <out>/<task>/<figure>.jpg and a copy of summary.json whose "figures" list names the JPGs, so that
import_aligned.py can read the staging folder as it read the earlier JPG renders.

Usage: python explorer/prep_renders.py <figures_pdf_dir> <out_dir> [dpi] [quality]
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SRC = Path(sys.argv[1]).expanduser().resolve(); OUT = Path(sys.argv[2]).expanduser().resolve()
DPI = int(sys.argv[3]) if len(sys.argv) > 3 else 100; Q = int(sys.argv[4]) if len(sys.argv) > 4 else 80


def rasterize(job):
    pdf, jpg = job
    stem = jpg.with_suffix("")
    subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", f"quality={Q}", "-r", str(DPI), "-singlefile", str(pdf), str(stem)], check=True)
    return jpg.stat().st_size


jobs = []
for d in sorted(p for p in SRC.iterdir() if p.is_dir() and (p / "summary.json").exists()):
    s = json.loads((d / "summary.json").read_text())
    (OUT / d.name).mkdir(parents=True, exist_ok=True)
    figs = []
    for f in s.get("figures", []):
        if f.lower().endswith(".pdf") and (d / f).exists():
            jpg = OUT / d.name / (Path(f).stem + ".jpg"); jobs.append((d / f, jpg)); figs.append(jpg.name)
    s["figures"] = figs
    (OUT / d.name / "summary.json").write_text(json.dumps(s))
with ThreadPoolExecutor(8) as ex:
    sizes = list(ex.map(rasterize, jobs))
print(f"{len(sizes)} images, {sum(sizes) / 1e6:.1f} MB, median {sorted(sizes)[len(sizes) // 2] / 1e3:.0f} kB, max {max(sizes) / 1e3:.0f} kB")
