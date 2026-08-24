import sys, time, glob
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from app import previews
files = glob.glob(r"D:\20260824 창무 국제 공연 예술제\photo\**\*.ARW", recursive=True)
print("파일수", len(files))
f = files[0]
t0 = time.time()
ok, meta = previews.build_previews(f, "stagetest")
print("build:", ok, round(time.time()-t0, 1), "s", meta.get("camera"), meta.get("iso"))
