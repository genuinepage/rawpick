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
HI_TARGET = 0.75
MID_TARGET = min(mv[len(mv) // 2], 0.30)
print("mid_target", round(MID_TARGET, 4))

for name in ["RY901138.ARW", "RY901234.ARW", "RY901330.ARW", "RY901145.ARW"]:
    row = db.execute("SELECT path, brightness, brightness_mid FROM photos WHERE filename=?",
                     (name,)).fetchone()
    p99, p50 = row["brightness"], row["brightness_mid"]
    lift = min(3.0, 0.8 * max(0.0, math.log2(HI_TARGET / p99))) if p99 and p99 > 0 else 0.0
    gamma = 1.0
    if p50 and p50 > 0:
        remain = max(0.0, math.log2(MID_TARGET / (p50 * 2.0 ** lift)))
        gamma = max(0.72, 1.0 - 0.25 * min(remain, 2.24))
    r = export_jpeg(row["path"], out / f"v4_{name}.jpg", 6.0, lift_ev=lift, mid_gamma=gamma)
    print(name, "p99=", round(p99, 3), "p50=", round(p50, 4),
          "lift=", round(lift, 2), "EV gamma=", round(gamma, 3),
          "->", round(r["size"] / 1048576, 2), "MB")
