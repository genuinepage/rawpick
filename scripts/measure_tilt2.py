"""수평 기울기 재측정 v2 — 강화 검출 + 장면 단위 전파.

같은 장면(동일 ISO·셔터·조리개 + 30초 이내 연속)에서는 카메라 기울기가
연속적이므로, 장면 내 검출값들의 중앙값을 검출 실패 컷에도 적용한다.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db, row_to_dict
from app import previews
from app.select import _parse_dt
from app.tilt import detect_tilt, correction_angle

if len(sys.argv) < 2:
    raise SystemExit("사용법: python scripts/measure_tilt2.py <RAW 폴더 경로>")
FOLDER = str(Path(sys.argv[1]).resolve())

db = get_db()
rows = [row_to_dict(r) for r in db.execute(
    "SELECT id, path, mtime, filename, meta FROM photos WHERE folder=? AND rating >= 2 "
    "ORDER BY filename", (FOLDER,)).fetchall()]

# 1) 개별 검출
detected = {}
for r in rows:
    pv = previews.preview_path(previews.cache_key(r["path"], r["mtime"]))
    detected[r["id"]] = detect_tilt(str(pv))

# 2) 장면 그룹핑 (export와 동일 규칙)
seq = sorted(rows, key=lambda r: (_parse_dt(r["meta"], r["mtime"]), r["filename"]))
scenes, cur, prev_key, prev_t = [], [], None, None
for r in seq:
    m = r["meta"]
    key = (m.get("iso"), m.get("shutter"), m.get("aperture"))
    t = _parse_dt(m, r["mtime"])
    if cur and (key != prev_key or t - prev_t > 30):
        scenes.append(cur)
        cur = []
    cur.append(r)
    prev_key, prev_t = key, t
if cur:
    scenes.append(cur)

# 3) 장면 중앙값 전파 — 핸드헬드는 컷마다 기울기가 다를 수 있으므로
#    장면 내 측정값이 서로 일치(표준편차 0.5° 이하)할 때만 전파한다.
n_direct = sum(1 for v in detected.values() if v is not None)
n_final = n_propagated = 0
for sc in scenes:
    vals = [detected[r["id"]] for r in sc if detected[r["id"]] is not None]
    med = None
    if len(vals) >= 2 and statistics.pstdev(vals) <= 0.5:
        med = statistics.median(vals)
    for r in sc:
        own = detected[r["id"]]
        tilt = own if own is not None else med
        db.execute("UPDATE photos SET tilt=? WHERE id=?", (tilt, r["id"]))
        if tilt is not None and correction_angle(tilt) != 0.0:
            n_final += 1
            if own is None:
                n_propagated += 1
db.commit()

print(f"총 {len(rows)}장 / 직접 검출 {n_direct}장 / 장면 {len(scenes)}개")
print(f"보정 대상(0.3~3°): {n_final}장 (그중 장면 전파 {n_propagated}장)")
rows2 = db.execute(
    "SELECT filename, tilt FROM photos WHERE folder=? AND rating >= 2 "
    "AND tilt IS NOT NULL AND ABS(tilt) BETWEEN 0.3 AND 3.0 "
    "ORDER BY ABS(tilt) DESC LIMIT 8", (FOLDER,)).fetchall()
for r in rows2:
    print(f"  {r['filename']}  {r['tilt']:+.2f}도")
