"""셀렉컷 밝기 측정 — 피사체 하이라이트(휘도 p99, 리니어) 기준.

p99는 피부·림라이트·흰 의상 등 '빛 받는 부분'의 밝기를 대변한다.
p90/p50은 배경 안개·조명 번짐에 속아서 실루엣 컷을 못 잡는다 (실측으로 확인).
"""
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db  # noqa: E402
from app import previews  # noqa: E402

FOLDER = r"D:\20260820 공연촬영\photo"

db = get_db()
rows = db.execute(
    "SELECT id, path, mtime, filename, rating, meta FROM photos "
    "WHERE folder=? AND rating >= 2 ORDER BY filename", (FOLDER,)).fetchall()

vals = []
for r in rows:
    tp = previews.thumb_path(previews.cache_key(r["path"], r["mtime"]))
    try:
        img = Image.open(tp).convert("L")
        arr = np.asarray(img, dtype=np.float32) / 255.0
        lin = arr ** 2.2
        p99 = float(np.percentile(lin, 99))
        p50 = float(np.percentile(lin, 50))
        db.execute("UPDATE photos SET brightness=?, brightness_mid=? WHERE id=?",
                   (p99, p50, r["id"]))
        vals.append((r["filename"], p99))
    except Exception as e:
        print("skip", r["filename"], e)
db.commit()

arr = np.array([v for _, v in vals])
ev = np.log2(np.maximum(arr, 1e-6))  # 상대 EV 스케일
print(f"측정 {len(arr)}장")
print(f"p90(리니어) 분포: 중앙값 {np.median(arr):.4f}  "
      f"10% {np.percentile(arr, 10):.4f}  25% {np.percentile(arr, 25):.4f}  "
      f"75% {np.percentile(arr, 75):.4f}")
med = np.median(arr)
for k, th in [("중앙값-1EV", med / 2), ("중앙값-1.5EV", med / 2**1.5), ("중앙값-2EV", med / 4)]:
    n = int((arr < th).sum())
    print(f"{k} ({th:.4f}) 미만: {n}장 ({n/len(arr)*100:.1f}%)")

# 어두운 컷 시간 분포 (파일명 순 = 시간 순)
th = med / 2**1.5
dark = [(f, v) for f, v in vals if v < th]
print(f"\n[중앙값-1.5EV 미만 어두운 컷 {len(dark)}장] 파일명 구간 분포:")
if dark:
    names = [f for f, _ in vals]
    idxs = [names.index(f) for f, _ in dark]
    buckets = {}
    for i in idxs:
        b = i // max(1, len(names) // 10)
        buckets[b] = buckets.get(b, 0) + 1
    for b in sorted(buckets):
        print(f"  구간 {b+1}/10 ({names[min(b*len(names)//10, len(names)-1)]}~): {buckets[b]}장")
    print("\n가장 어두운 10장:")
    for f, v in sorted(dark, key=lambda x: x[1])[:10]:
        print(f"  {f}  p90={v:.4f}  (중앙값 대비 {np.log2(v/med):+.1f}EV)")
