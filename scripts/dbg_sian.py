import math
import sys
from pathlib import Path

import cv2
import numpy as np
import rawpy
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db  # noqa: E402
from app import retouch  # noqa: E402

OUT = Path(r"C:\Users\genuine\AppData\Local\Temp\claude"
           r"\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
db = get_db()
r = db.execute("SELECT path, brightness FROM photos WHERE filename='RY905913.ARW'").fetchone()
deficit = max(0.0, math.log2(0.75 / r["brightness"]))
lift = min(3.5, 0.8 * deficit + 0.75 * min(1.0, deficit / 0.5))
pp = {"use_camera_wb": True, "no_auto_bright": True, "output_bps": 8}
if lift > 0.01:
    pp["exp_shift"] = float(2.0 ** lift)
with rawpy.imread(r["path"]) as raw:
    rgb = raw.postprocess(**pp)
print("shape:", rgb.shape, "lift:", round(lift, 2))

boxes = retouch._find_face_boxes(rgb)
print("YuNet boxes:", [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in boxes])
faces = retouch._detect(rgb)
for pts in faces:
    oval = pts[retouch.FACE_OVAL]
    print("landmark face: x", int(oval[:, 0].min()), "-", int(oval[:, 0].max()),
          "y", int(oval[:, 1].min()), "-", int(oval[:, 1].max()))

vis = rgb.copy()
for b in boxes:
    cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[0] + b[2]), int(b[1] + b[3])),
                  (255, 0, 0), 12)
for pts in faces:
    oval = pts[retouch.FACE_OVAL].astype(np.int32)
    cv2.polylines(vis, [oval], True, (0, 255, 0), 12)
im = Image.fromarray(vis)
im.thumbnail((1400, 1400))
im.save(OUT / "dbg_sian_vis.jpg", quality=85)
print("저장")
