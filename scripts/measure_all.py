"""폴더 전체(별점 무관) 밝기 미측정분 측정 — 재셀렉 후 측정 공백 방지."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db  # noqa: E402
from app import previews  # noqa: E402

FOLDER = str(Path(sys.argv[1]).resolve())
db = get_db()
rows = db.execute(
    "SELECT id, path, mtime FROM photos WHERE folder=? AND preview_ok=1 "
    "AND brightness IS NULL", (FOLDER,)).fetchall()
print(f"미측정 {len(rows)}장")
for r in rows:
    tp = previews.thumb_path(previews.cache_key(r["path"], r["mtime"]))
    try:
        arr = np.asarray(Image.open(tp).convert("L"), dtype=np.float32) / 255.0
        lin = arr ** 2.2
        db.execute("UPDATE photos SET brightness=?, brightness_mid=? WHERE id=?",
                   (float(np.percentile(lin, 99)), float(np.percentile(lin, 50)), r["id"]))
    except Exception:
        pass
db.commit()
print("측정 완료")
