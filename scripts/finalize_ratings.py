"""최종 셀렉 확정 — 1~5 폴더에 남은 컷은 ★4 승격, 탈락한 기존 셀렉은 ★1 하향.

DB와 XMP 사이드카 모두 갱신 → 캡처원/라이트룸에서 ★4 필터가 최종 셀렉과 일치.
"""
import sys
from pathlib import Path
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app import xmp

FOLDER = r"D:\20260820 공연촬영\photo"
SELECTS = Path(r"D:\20260820 공연촬영\photo\_export\selects")

final = {p.stem for d in SELECTS.iterdir() if d.is_dir()
         for p in d.glob("*.jpg")}
print(f"확정 셀렉: {len(final)}장")

db = get_db()
rows = db.execute("SELECT id, path, filename, rating, color_label FROM photos "
                  "WHERE folder=?", (FOLDER,)).fetchall()
n_up = n_down = 0
for r in rows:
    stem = Path(r["filename"]).stem
    if stem in final:
        if r["rating"] != 4:
            db.execute("UPDATE photos SET rating=4 WHERE id=?", (r["id"],))
            xmp.write_sidecar(r["path"], 4, r["color_label"])
            n_up += 1
    elif r["rating"] >= 2:  # 내보냈지만 탈락한 컷
        db.execute("UPDATE photos SET rating=1 WHERE id=?", (r["id"],))
        xmp.write_sidecar(r["path"], 1, r["color_label"])
        n_down += 1
db.commit()
print(f"★4 승격 {n_up}장 / 탈락 하향(★1) {n_down}장")
