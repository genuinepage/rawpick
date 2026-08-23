"""레퍼런스 컷 휘도 분포 비교 — 사용자 체감 밝기와 일치하는 지표 탐색.

RY901138: 실루엣+백라이트 안개 (사용자: 많이 밝아져야)
RY901234: 스포트라이트 솔로 (사용자: 조금 더 밝아져야)
RY901145: 잘 나온 밝기 (목표 기준)
"""
import sys
import numpy as np
from PIL import Image
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app import previews

db = get_db()
for name in ["RY901138.ARW", "RY901234.ARW", "RY901145.ARW"]:
    row = db.execute("SELECT path, mtime FROM photos WHERE filename=?", (name,)).fetchone()
    tp = previews.thumb_path(previews.cache_key(row["path"], row["mtime"]))
    arr = np.asarray(Image.open(tp).convert("L"), dtype=np.float32) / 255.0
    lin = arr ** 2.2
    ps = {p: float(np.percentile(lin, p)) for p in (25, 50, 75, 90, 95, 99)}
    # 중앙 50% 크롭 (피사체 가중)
    h, w = lin.shape
    c = lin[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    cps = {p: float(np.percentile(c, p)) for p in (50, 75, 90)}
    print(name)
    print("  전체:", {k: round(v, 4) for k, v in ps.items()})
    print("  중앙크롭:", {k: round(v, 4) for k, v in cps.items()})
