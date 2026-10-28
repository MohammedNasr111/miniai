"""Re-score Round 8b measure JSON under Round 8c rules (no re-run)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "logs" / "round8b_part4_measure.json"
out = ROOT / "logs" / "round8b_part4_measure_rescored_r8c.md"
d = json.loads(src.read_text(encoding="utf-8"))
rows = d["rows"]
gemini = [r for r in rows if str(r.get("answered_by") or "") == "gemini"]
excl = [r for r in rows if str(r.get("answered_by") or "") != "gemini"]
safety = [r for r in gemini if r.get("kind") == "safety"]
hard = [r for r in gemini if r.get("kind") == "hard"]
sp = sum(1 for r in safety if r["pass"])
st = len(safety)
hp = sum(1 for r in hard if r["pass"])
ht = len(hard)
by: dict[str, int] = {}
for r in hard:
    by[r["id"]] = by.get(r["id"], 0) + (1 if r["pass"] else 0)
lines = [
    "# Round 8b measure re-scored under Round 8c rules",
    "",
    "Only rows with `answered_by==\"gemini\"` count. Original live run was not re-executed.",
    "",
    f"- Gemini-scored safety: **{sp}/{st}**",
    f"- Gemini-scored hard: **{hp}/{ht}** (by task: {by})",
    f"- Excluded rows: **{len(excl)}**",
    "",
    "## Excluded",
    "",
    "| id | answered_by | pass |",
    "|---|---|---:|",
]
for r in excl:
    lines.append(f"| {r['id']} | {r.get('answered_by')} | {r.get('pass')} |")
lines.append("")
out.write_text("\n".join(lines), encoding="utf-8")
print(f"gemini_rows={len(gemini)} excluded={len(excl)} safety={sp}/{st} hard={hp}/{ht}")
print("WROTE", out)
