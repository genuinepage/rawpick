import sys, json, math
from collections import Counter
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
db = get_db()
rows = db.execute("SELECT brightness, meta FROM photos WHERE folder=? AND rating=4",
                  (r"D:\20260820 공연촬영\photo",)).fetchall()
c = Counter()
for r in rows:
    m = json.loads(r["meta"] or "{}")
    iso, p99 = m.get("iso"), r["brightness"]
    if not iso or not p99 or p99 <= 0:
        c["?"] += 1; continue
    d = max(0.0, math.log2(0.75 / p99))
    lift = min(3.5, 0.8 * d + 0.75 * min(1.0, d / 0.5))
    eff = iso * 2 ** lift
    if eff >= 8000: c[">=8000 (AI)"] += 1
    elif eff >= 5000: c["5000-8000"] += 1
    elif eff >= 3200: c["3200-5000"] += 1
    else: c["<3200"] += 1
for k in [">=8000 (AI)", "5000-8000", "3200-5000", "<3200", "?"]:
    print(k, c[k])
