"""인물 보정 시안 — 피사체 크기별(클로즈업/미들/풀샷) 전후 비교 생성.

각 컷을 최종 파이프라인(리프트+AI NR+질감복원+톤)으로 렌더한 뒤
보정 없음 / 피부25%+턱선0.7% 두 버전의 얼굴 중심 100% 크롭 저장.
"""
import json
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
from app import previews  # noqa: E402

OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
FOLDER = r"D:\20260820 공연촬영\photo"

db = get_db()

# ---- 1) 얼굴 크기 스캔 (프리뷰에서 → 풀해상도 환산) ----
rows = db.execute(
    "SELECT path, mtime, filename, brightness, brightness_mid, meta FROM photos "
    "WHERE folder=? AND rating=4 AND face_count>=1 AND brightness > 0.25 "
    "ORDER BY filename", (FOLDER,)).fetchall()
step = max(1, len(rows) // 120)
buckets = {"closeup": [], "mid": [], "full": []}
for r in rows[::step]:
    pv = previews.preview_path(previews.cache_key(r["path"], r["mtime"]))
    img = np.asarray(Image.open(pv).convert("RGB"))
    boxes = retouch._find_face_boxes(img)
    if not boxes:
        continue
    fh_full = max(b[3] for b in boxes) * (6012 / img.shape[1])
    if fh_full >= 550:
        buckets["closeup"].append((r, fh_full))
    elif fh_full >= 220:
        buckets["mid"].append((r, fh_full))
    elif fh_full >= 90:
        buckets["full"].append((r, fh_full))

mv = sorted(x[0] for x in db.execute(
    "SELECT brightness_mid FROM photos WHERE folder=? AND rating >= 2 "
    "AND brightness_mid IS NOT NULL", (FOLDER,)))
MID_TARGET = min(mv[len(mv) // 2], 0.30)
ref = db.execute("SELECT path FROM photos WHERE folder=? AND rating>=2 AND brightness>0.5 "
                 "AND json_extract(meta,'$.iso')<=1000 LIMIT 1", (FOLDER,)).fetchone()
with rawpy.imread(ref["path"]) as raw:
    TEX_TARGET = texture.fine_std(raw.postprocess(
        use_camera_wb=True, no_auto_bright=True, output_bps=8))

for bucket, items in buckets.items():
    items.sort(key=lambda x: -x[1])
    for r, fh in items[:2]:
        p99, p50 = r["brightness"], r["brightness_mid"]
        deficit = max(0.0, math.log2(0.75 / p99)) if p99 and p99 > 0 else 0.0
        lift = min(3.5, 0.8 * deficit + 0.75 * min(1.0, deficit / 0.5))
        gamma = 1.0
        if p50 and p50 > 0:
            remain = max(0.0, math.log2(MID_TARGET / (p50 * 2.0 ** lift)))
            gamma = max(0.72, 1.0 - 0.25 * min(remain, 2.24))
        iso = json.loads(r["meta"] or "{}").get("iso") or 0
        eff = iso * 2 ** lift
        pp = {"use_camera_wb": True, "no_auto_bright": True, "output_bps": 8}
        if lift > 0.01:
            pp["exp_shift"] = float(2.0 ** lift)
            pp["exp_preserve_highlights"] = 0.9
        with rawpy.imread(r["path"]) as raw:
            rgb = raw.postprocess(**pp)
        if eff >= 3200:
            den = ai_denoise.denoise_rgb(rgb)
            rgb_final = texture.restore(den, rgb, TEX_TARGET)
        else:
            rgb_final = rgb
        ret, stats = retouch.retouch(rgb_final.copy())
        lut = _tone_lut(gamma, black_point=min(0.10, 0.035 * lift))
        boxes = retouch._find_face_boxes(rgb_final)
        if boxes:
            bx, by, bw, bh = max(boxes, key=lambda b: b[2] * b[3])
            cx, cy = int(bx + bw / 2), int(by + bh / 2)
        else:
            cy, cx = rgb.shape[0] // 2, rgb.shape[1] // 2
        print("  크롭중심", cx, cy, "이미지", rgb.shape[1], "x", rgb.shape[0],
              "박스", [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in boxes])
        cw, ch = (1100, 800)
        x0 = max(0, min(rgb.shape[1] - cw, cx - cw // 2))
        y0 = max(0, min(rgb.shape[0] - ch, cy - ch // 3))
        stem = Path(r["filename"]).stem
        for tag, img in [("off", rgb_final), ("on", ret)]:
            Image.fromarray(lut[img][y0:y0 + ch, x0:x0 + cw]).save(
                OUT / f"sian_{bucket}_{stem}_{tag}.jpg", quality=92)
        print(f"{bucket} {stem} 얼굴{int(fh)}px eff{int(eff)} 보정: {stats}")
