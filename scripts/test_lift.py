import sys
from pathlib import Path
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
row = db.execute("SELECT path, brightness FROM photos WHERE filename='RY901128.ARW'").fetchone()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
r2 = export_jpeg(row["path"], out / "lift_v2.jpg", 6.0, lift_ev=1.76)
print("v2", round(r2["size"] / 1048576, 2), "MB")
