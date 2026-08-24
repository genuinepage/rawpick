import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from app.catalog import get_db
db = get_db()
for r in db.execute("SELECT folder, COUNT(*) c, SUM(preview_ok) p FROM photos GROUP BY folder"):
    print(repr(r["folder"]), r["c"], r["p"])
