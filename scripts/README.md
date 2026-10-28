# Agent Trace Explorer

A local browser view of the agent strategies bundle.

## Run it

From the bundle root (the folder that holds `runs/` and `scores/`):

    python explorer/tag_runs.py .        # about 3 minutes; writes explorer/data/*.json
    python -m http.server 8765 --bind 127.0.0.1

Then open http://127.0.0.1:8765/explorer/ . Link straight to a run with `#<run_id>`, or to a tab with `#strategies`, `#figures`, and so on.

## Tabs

- Overview: outcomes per model, the score spread per model and condition, effort (time, cost, tool calls).
- Tasks: task by model heatmap, next to the best published and best naive baseline on each task.
- Strategies: what each model tried versus what its submitted code uses, grouped by pipeline stage
  (the exploration-space and final-approach tables from the Genomics notes), plus how each keyword in
  the final code relates to the within-task percentile, what the submission is, and the order in which packages were tried.
- Process: the phase share over the course of a run (the layout of RCT_Bench fig10A), wall time per phase,
  working habits, and the phase mix by score tercile.
- Runs: a filterable list. Click a run to see its phase strip, keywords, decision quotes, the full trace and the final code.

## How tags are made (heuristic)

`tag_runs.py` gives every tool call one phase: inspect, set up, preprocess, try a method, evaluate, write the submission,
validate, or wait. Keywords are regexes over code. Plain shell inspection (`ls`, `grep` over a package) does not count as trying a method.
Running a script inherits the tags of the step that wrote it. Edit the `KW` list in `tag_runs.py` to change the taxonomy.
Codex `apply_patch` events have no contents, so Codex exploration is undercounted.
The within-task percentile ranks a run among all scored agent runs on the same task.
