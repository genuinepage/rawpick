import json
import math
import sys
import time
from pathlib import Path
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")

for name in ["RY901493.ARW", "RY901502.ARW"]:
    row = db.execute("SELECT path, brightness, brightness_mid, meta FROM photos "
                     "WHERE filename=?", (name,)).fetchone()
    meta = json.loads(row["meta"] or "{}")
    iso = meta.get("iso", 0)
    p99 = row["brightness"]
    lift = min(3.0, 0.8 * max(0.0, math.log2(0.75 / p99))) if p99 and p99 > 0 else 0.0
    eff = iso * 2 ** lift
    nr = 3 if eff >= 12800 else 2 if eff >= 10000 else 1 if eff >= 8000 else 0
    t0 = time.time()
    r = export_jpeg(row["path"], out / f"nr{nr}_{name}.jpg", 6.0,
                    lift_ev=lift, nr_level=nr)
    print(name, "iso=", iso, "lift=", round(lift, 2), "eff_iso=", int(eff),
          "nr=", nr, f"{time.time()-t0:.1f}s", round(r["size"] / 1048576, 2), "MB")
