import json
import math
import sys
from pathlib import Path
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
FOLDER = r"D:\20260820 공연촬영\photo"

mv = sorted(r[0] for r in db.execute(
    "SELECT brightness_mid FROM photos WHERE folder=? AND rating IN (2,3) "
    "AND brightness_mid IS NOT NULL", (FOLDER,)))
MID_TARGET = min(mv[len(mv) // 2], 0.30)

row = db.execute("SELECT path, brightness, brightness_mid, meta FROM photos "
                 "WHERE filename='RY902605.ARW'").fetchone()
p99, p50 = row["brightness"], row["brightness_mid"]
deficit = max(0.0, math.log2(0.75 / p99)) if p99 and p99 > 0 else 0.0
lift = min(3.5, 0.8 * deficit + 0.75 * min(1.0, deficit / 0.5))
gamma = 1.0
if p50 and p50 > 0:
    remain = max(0.0, math.log2(MID_TARGET / (p50 * 2.0 ** lift)))
    gamma = max(0.72, 1.0 - 0.25 * min(remain, 2.24))
iso = json.loads(row["meta"] or "{}").get("iso") or 0
eff = iso * 2 ** lift
nr = 5 if eff >= 20000 else 4 if eff >= 12800 else 3 if eff >= 10000 else \
    2 if eff >= 8000 else 1 if eff >= 5000 else 0
r = export_jpeg(row["path"], out / "lamp_final.jpg", 6.0,
                lift_ev=lift, mid_gamma=gamma, nr_level=nr)
print("p99=", round(p99, 3), "lift=", round(lift, 2), "gamma=", round(gamma, 3),
      "nr=", nr, round(r["size"] / 1048576, 2), "MB")
