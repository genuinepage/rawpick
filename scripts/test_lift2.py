import math
import sys
from pathlib import Path
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")

bvals = sorted(r[0] for r in db.execute(
    "SELECT brightness FROM photos WHERE folder=? AND rating IN (2,3) "
    "AND brightness IS NOT NULL", (r"D:\20260820 공연촬영\photo",)))
med = bvals[len(bvals) // 2]
print("median", round(med, 4))

for name in ["RY901138.ARW", "RY901234.ARW"]:
    row = db.execute("SELECT path, brightness FROM photos WHERE filename=?", (name,)).fetchone()
    b = row["brightness"]
    deficit = math.log2(med / b) if b and b > 0 else 0
    lift = min(3.0, 0.85 * max(0.0, deficit))
    r = export_jpeg(row["path"], out / f"v3_{name}.jpg", 6.0, lift_ev=lift)
    print(name, "p90=", round(b, 4), "deficit=", round(deficit, 2), "EV lift=", round(lift, 2),
          "->", round(r["size"] / 1048576, 2), "MB")
