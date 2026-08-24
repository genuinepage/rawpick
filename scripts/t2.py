import glob, rawpy, traceback
files = glob.glob(r"D:\20260824 창무 국제 공연 예술제\photo\**\*.ARW", recursive=True)
f = files[0]
print(f)
import os
print("size:", os.path.getsize(f) / 1048576, "MB")
try:
    with rawpy.imread(f) as raw:
        print("open OK", raw.sizes.width, raw.sizes.height)
        t = raw.extract_thumb()
        print("thumb", t.format, len(t.data))
except Exception:
    traceback.print_exc()
