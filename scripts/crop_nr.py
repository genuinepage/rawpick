import json
import math
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db

out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
# NR 적용본 100% 크롭 (피사체 주변)
img = Image.open(out / "nr3_RY901493.ARW.jpg")
w, h = img.size
img.crop((w // 2 - 600, h // 4, w // 2 + 600, h // 4 + 800)).save(out / "crop_nr3.jpg", quality=92)

# NR 단계 분포 예측
db = get_db()
rows = db.execute("SELECT brightness, meta FROM photos WHERE folder=? AND rating IN (2,3)",
                  (r"D:\20260820 공연촬영\photo",)).fetchall()
dist = {0: 0, 1: 0, 2: 0, 3: 0}
for r in rows:
    iso = json.loads(r["meta"] or "{}").get("iso") or 0
    p99 = r["brightness"]
    lift = min(3.0, 0.8 * max(0.0, math.log2(0.75 / p99))) if p99 and p99 > 0 else 0.0
    eff = iso * 2 ** lift
    nr = 3 if eff >= 12800 else 2 if eff >= 10000 else 1 if eff >= 8000 else 0
    dist[nr] += 1
print("NR 분포:", dist)
