"""NR 경계(실효 8000) 양쪽 비교 — 고전 NR(미만) vs AI(이상) 역전 여부 확인."""
import json
import math
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app.export import export_jpeg

db = get_db()
OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
FOLDER = r"D:\20260820 공연촬영\photo"

mv = sorted(r[0] for r in db.execute(
    "SELECT brightness_mid FROM photos WHERE folder=? AND rating >= 2 "
    "AND brightness_mid IS NOT NULL", (FOLDER,)))
MID_TARGET = min(mv[len(mv) // 2], 0.30)

rows = db.execute("SELECT path, filename, brightness, brightness_mid, meta FROM photos "
                  "WHERE folder=? AND rating=4", (FOLDER,)).fetchall()

below = above = None
for r in rows:
    m = json.loads(r["meta"] or "{}")
    iso = m.get("iso")
    p99 = r["brightness"]
    if not iso or not p99 or p99 <= 0:
        continue
    deficit = max(0.0, math.log2(0.75 / p99))
    lift = min(3.5, 0.8 * deficit + 0.75 * min(1.0, deficit / 0.5))
    eff = iso * 2 ** lift
    if below is None and 3800 <= eff < 4800:
        below = (r, lift, eff, 1)
    if above is None and 5200 <= eff < 6500:
        above = (r, lift, eff, 2)
    if below and above:
        break

for label, (r, lift, eff, nr) in [("below", below), ("above", above)]:
    p50 = r["brightness_mid"]
    gamma = 1.0
    if p50 and p50 > 0:
        remain = max(0.0, math.log2(MID_TARGET / (p50 * 2.0 ** lift)))
        gamma = max(0.72, 1.0 - 0.25 * min(remain, 2.24))
    export_jpeg(r["path"], OUT / f"bnd_{label}.jpg", 10.0,
                lift_ev=lift, mid_gamma=gamma, nr_level=nr)
    img = Image.open(OUT / f"bnd_{label}.jpg")
    w, h = img.size
    img.crop((w // 6, h // 8, w // 6 + 1200, h // 8 + 800)).save(
        OUT / f"bnd_{label}_crop.jpg", quality=92)
    print(label, r["filename"], "iso", json.loads(r["meta"])["iso"],
          "lift", round(lift, 2), "eff", int(eff), "nr", nr)
