import sys, json
from collections import Counter
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db

db = get_db()
rows = db.execute("SELECT meta, brightness, rating FROM photos WHERE folder=?",
                  (r"D:\20260820 공연촬영\photo",)).fetchall()
combo = Counter()
iso_c = Counter()
dark = Counter()
tot = Counter()
for r in rows:
    m = json.loads(r["meta"] or "{}")
    key = f'{m.get("shutter")} {m.get("aperture")}'
    combo[key] += 1
    iso = m.get("iso")
    if iso:
        iso_c[iso] += 1
    b = r["brightness"]
    if b is not None and m.get("shutter"):
        tot[key] += 1
        if b < 0.18:  # 하이라이트 p99가 목표(0.75) 대비 2EV 이상 부족
            dark[key] += 1
print("셔터+조리개 조합:", combo.most_common(6))
print("ISO 분포:", sorted(iso_c.items()))
print("확정셀렉 중 -2EV 이상 노출부족 비율:")
for k, t in tot.most_common(5):
    print(f"  {k}: {dark[k]}/{t} ({dark[k]/t*100:.0f}%)")
