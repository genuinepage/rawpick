import sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from app.catalog import get_db
from app import previews
db = get_db()
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
for n in ["RY905913.ARW", "RY905126.ARW", "RY901984.ARW"]:
    r = db.execute("SELECT path, mtime FROM photos WHERE filename=?", (n,)).fetchone()
    shutil.copy(previews.thumb_path(previews.cache_key(r["path"], r["mtime"])), out / f"chk2_{n}.jpg")
print("ok")
