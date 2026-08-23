import sys, shutil
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app import previews

db = get_db()
out = (r"C:\Users\genuine\AppData\Local\Temp\claude"
       r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
rows = db.execute(
    "SELECT filename, path, mtime, brightness FROM photos "
    "WHERE folder=? AND rating IN (2,3) AND brightness IS NOT NULL ORDER BY brightness",
    (r"D:\20260820 공연촬영\photo",)).fetchall()
med = rows[len(rows) // 2]["brightness"]
darker2ev = [r for r in rows if r["brightness"] < med / 4]
near = [r for r in rows if r["brightness"] < med / 2 ** 1.5]
picks = [rows[0], darker2ev[len(darker2ev) // 2], near[-1]]
for r in picks:
    tp = previews.thumb_path(previews.cache_key(r["path"], r["mtime"]))
    dst = f"{out}\\dark_{r['brightness']:.4f}_{r['filename']}.jpg"
    shutil.copy(tp, dst)
    print(r["filename"], round(r["brightness"], 4))
