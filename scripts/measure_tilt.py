"""셀렉컷(★2+★3) 수평 기울기 측정 → DB 저장 + 보정 대상 요약."""
import sys
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app import previews
from app.tilt import detect_tilt, correction_angle

FOLDER = r"D:\20260820 공연촬영\photo"

db = get_db()
rows = db.execute(
    "SELECT id, path, mtime, filename FROM photos WHERE folder=? AND rating IN (2,3) "
    "ORDER BY filename", (FOLDER,)).fetchall()

n_detected = n_correct = 0
targets = []
for r in rows:
    pv = previews.preview_path(previews.cache_key(r["path"], r["mtime"]))
    tilt = detect_tilt(str(pv))
    db.execute("UPDATE photos SET tilt=? WHERE id=?", (tilt, r["id"]))
    if tilt is not None:
        n_detected += 1
        if correction_angle(tilt) != 0.0:
            n_correct += 1
            targets.append((r["filename"], tilt))
db.commit()

print(f"측정 {len(rows)}장 / 기준선 검출 {n_detected}장 / 보정 대상(0.3~3°) {n_correct}장")
print("\n보정 대상 예시 (기울기 큰 순 10장):")
for f, t in sorted(targets, key=lambda x: -abs(x[1]))[:10]:
    print(f"  {f}  {t:+.2f}도")
import json
from pathlib import Path
Path(r"C:\projects\rawpick\scripts\tilt_targets.json").write_text(
    json.dumps([f for f, _ in targets]), encoding="utf-8")
