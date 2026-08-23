"""fp16+배치 ai_denoise 속도·품질 검증."""
import sys
import time
from pathlib import Path
import rawpy
from PIL import Image
sys.path.insert(0, r"C:\projects\rawpick")
from app.catalog import get_db
from app import ai_denoise

OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
db = get_db()
row = db.execute("SELECT path FROM photos WHERE filename='RY901493.ARW'").fetchone()
with rawpy.imread(row["path"]) as raw:
    rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8,
                          exp_shift=float(2.0 ** 3.5), exp_preserve_highlights=0.9)
# 워밍업(모델 로드) 분리 측정
t0 = time.time()
den = ai_denoise.denoise_rgb(rgb)
t_first = time.time() - t0
t0 = time.time()
den = ai_denoise.denoise_rgb(rgb)
t_second = time.time() - t0
print(f"1회차(모델로드 포함) {t_first:.1f}s / 2회차 {t_second:.1f}s")
img = Image.fromarray(den)
w, h = img.size
img.crop((w // 2 - 600, h // 4, w // 2 + 600, h // 4 + 800)).save(
    OUT / "crop_fp16.jpg", quality=92)
