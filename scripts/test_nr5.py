import sys
import time
from pathlib import Path
from PIL import Image
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
row = db.execute("SELECT path FROM photos WHERE filename='RY901493.ARW'").fetchone()
t0 = time.time()
export_jpeg(row["path"], out / "nr5_RY901493.jpg", 6.0, lift_ev=3.0, nr_level=5)
print("nr5:", round(time.time() - t0, 1), "s")
img = Image.open(out / "nr5_RY901493.jpg")
w, h = img.size
img.crop((w // 2 - 600, h // 4, w // 2 + 600, h // 4 + 800)).save(out / "crop_nr5.jpg", quality=92)
