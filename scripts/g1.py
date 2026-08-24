import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from app.catalog import get_db
db = get_db()
rows = db.execute("SELECT filename, rating, cull_flag, meta FROM photos "
                  "WHERE folder=? AND filename >= 'DSC03557' ORDER BY filename",
                  (r"D:\20260824 창무 국제 공연 예술제\photo",)).fetchall()
import json
print("총", len(rows), "장 /", rows[0]["filename"], "~", rows[-1]["filename"])
print("기존 별점 분포:", {r: sum(1 for x in rows if x["rating"] == r) for r in (0, 1, 2, 3)})
print("불량 플래그:", sum(1 for x in rows if x["cull_flag"]))
times = [json.loads(x["meta"] or "{}").get("datetime") for x in rows]
print("시간:", times[0], "~", times[-1])
