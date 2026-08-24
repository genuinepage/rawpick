"""피부 정돈 강도 3단 비교 — 뺨 타이트 크롭 (무보정 / 25% / 40%)."""
import math
import sys
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db  # noqa: E402
from app import ai_denoise, retouch, texture  # noqa: E402
from app.export import _tone_lut  # noqa: E402

OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
db = get_db()
r = db.execute("SELECT path, brightness, brightness_mid FROM photos "
               "WHERE filename='RY905126.ARW'").fetchone()
deficit = max(0.0, math.log2(0.75 / r["brightness"]))
lift = min(3.5, 0.8 * deficit + 0.75 * min(1.0, deficit / 0.5))
with rawpy.imread(r["path"]) as raw:
    rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8,
                          exp_shift=float(2.0 ** lift), exp_preserve_highlights=0.9)
den = ai_denoise.denoise_rgb(rgb)
base = texture.restore(den, rgb, None)

faces = retouch._detect(base)
pts, yaw = max(faces, key=lambda f: np.ptp(f[0][retouch.FACE_OVAL][:, 1]))
oval = pts[retouch.FACE_OVAL]
# 뺨 중심 크롭 (얼굴 중앙 아래쪽)
cx = int(oval[:, 0].mean())
cy = int(oval[:, 1].mean() + np.ptp(oval[:, 1]) * 0.15)
cw, ch = 700, 500
x0, y0 = max(0, cx - cw // 2), max(0, cy - ch // 2)

lut = _tone_lut(0.86, black_point=min(0.10, 0.035 * lift))
for name, blend in [("s0_off", None), ("s1_25", 0.25), ("s2_40", 0.40)]:
    img = base if blend is None else retouch._smooth_skin(base, pts, blend)
    crop = Image.fromarray(lut[img][y0:y0 + ch, x0:x0 + cw])
    crop = crop.resize((cw * 2, ch * 2), Image.LANCZOS)  # 200% 확대로 차이 가시화
    crop.save(OUT / f"skin_{name}.jpg", quality=92)
    print(name, "저장")
