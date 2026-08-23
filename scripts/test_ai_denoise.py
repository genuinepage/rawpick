"""SCUNet AI 디노이즈 테스트 — 기존 NR5(고전) 대비 비교.

RTX 3090에서 24MP 풀해상도를 512px 타일(32px 오버랩)로 나눠 추론.
"""
import io
import sys
import time
from pathlib import Path

import numpy as np
import rawpy
import torch
from PIL import Image

sys.path.insert(0, r"C:\projects\rawpick")
sys.path.insert(0, r"C:\projects\rawpick\third_party\SCUNet")
from models.network_scunet import SCUNet  # noqa: E402
from app.catalog import get_db  # noqa: E402
from app.export import _tone_lut  # noqa: E402

OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
WEIGHTS = Path.home() / ".rawpick" / "models" / "scunet_color_real_psnr.pth"
LIFT_EV = 3.5
TILE, OVERLAP = 512, 32

db = get_db()
row = db.execute("SELECT path FROM photos WHERE filename='RY901493.ARW'").fetchone()

t0 = time.time()
with rawpy.imread(row["path"]) as raw:
    rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8,
                          exp_shift=float(2.0 ** LIFT_EV), exp_preserve_highlights=0.9)
print(f"디코드 {time.time()-t0:.1f}s, {rgb.shape}")

device = "cuda" if torch.cuda.is_available() else "cpu"
model = SCUNet(in_nc=3, config=[4, 4, 4, 4, 4, 4, 4], dim=64)
model.load_state_dict(torch.load(WEIGHTS, map_location="cpu"), strict=True)
model = model.to(device).eval()
print("모델 로드:", device)

t0 = time.time()
img = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1)
_, H, W = img.shape
out = torch.zeros_like(img)
weight = torch.zeros(1, H, W)
step = TILE - 2 * OVERLAP
with torch.no_grad():
    ys = list(range(0, max(1, H - TILE + 1), step)) + [max(0, H - TILE)]
    xs = list(range(0, max(1, W - TILE + 1), step)) + [max(0, W - TILE)]
    for y in sorted(set(ys)):
        for x in sorted(set(xs)):
            tile = img[:, y:y + TILE, x:x + TILE].unsqueeze(0).to(device)
            pred = model(tile).squeeze(0).cpu().clamp(0, 1)
            out[:, y:y + TILE, x:x + TILE] += pred
            weight[:, y:y + TILE, x:x + TILE] += 1.0
out = out / weight
elapsed = time.time() - t0
print(f"SCUNet 추론 {elapsed:.1f}s")

den = (out.permute(1, 2, 0).numpy() * 255.0 + 0.5).astype(np.uint8)
den = _tone_lut(0.86, black_point=min(0.10, 0.035 * LIFT_EV))[den]

img_out = Image.fromarray(den)
buf = io.BytesIO()
img_out.save(buf, "JPEG", quality=90, subsampling=1)
(OUT / "ai_denoise_full.jpg").write_bytes(buf.getvalue())
w, h = img_out.size
img_out.crop((w // 2 - 600, h // 4, w // 2 + 600, h // 4 + 800)).save(
    OUT / "crop_ai.jpg", quality=92)
view = img_out.copy()
view.thumbnail((2000, 2000))
view.save(OUT / "ai_view.jpg", quality=85)
print("저장 완료", round(len(buf.getvalue()) / 1048576, 2), "MB")
