"""단체/개인사진 구간 분류·출력 — 얼굴 과노출 자동 압축 포함 (리뷰용 1MB).

사용: python scripts/group_photos.py <RAW 폴더> <시작파일명> <출력폴더명>
"""
import io
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db  # noqa: E402
from app import previews, retouch, xmp  # noqa: E402

FOLDER = str(Path(sys.argv[1]).resolve())
START = sys.argv[2]
OUT_NAME = sys.argv[3]
OUT_DIR = Path(FOLDER) / "_export" / "selects" / OUT_NAME
OUT_DIR.mkdir(parents=True, exist_ok=True)

RESIZE = 3200
MAX_BYTES = int(1.0 * 1024 * 1024)
FACE_HOT_P95 = 232   # 얼굴 p95가 이 이상이면 과노출로 판정
KNEE = 205           # 압축 시작점

db = get_db()
rows = db.execute(
    "SELECT id, path, filename, brightness, color_label, cull_flag FROM photos "
    "WHERE folder=? AND filename >= ? ORDER BY filename", (FOLDER, START)).fetchall()
targets = [r for r in rows if not r["cull_flag"]]
print(f"구간 {len(rows)}장 중 선발 {len(targets)}장 (불량 {len(rows)-len(targets)} 제외)")

for r in targets:  # 별점 승격 + XMP
    db.execute("UPDATE photos SET rating=3, ai_pick=3 WHERE id=?", (r["id"],))
    xmp.write_sidecar(r["path"], 3, r["color_label"])
for r in rows:
    if r["cull_flag"]:
        db.execute("UPDATE photos SET rating=0 WHERE id=?", (r["id"],))
db.commit()


def compress_hot_faces(rgb: np.ndarray) -> int:
    """과노출 얼굴의 하이라이트를 부드럽게 압축. 처리한 얼굴 수 반환. (제자리 수정)"""
    n = 0
    l = rgb.astype(np.float32).mean(axis=2)
    for (bx, by, bw, bh) in retouch._find_face_boxes(rgb):
        x0, y0 = max(0, int(bx)), max(0, int(by))
        x1 = min(rgb.shape[1], int(bx + bw))
        y1 = min(rgb.shape[0], int(by + bh))
        roi_l = l[y0:y1, x0:x1]
        if roi_l.size == 0 or np.percentile(roi_l, 95) < FACE_HOT_P95:
            continue
        # 얼굴 중심 타원 페더 마스크
        mh, mw = y1 - y0, x1 - x0
        yy, xx = np.mgrid[0:mh, 0:mw].astype(np.float32)
        d = (((xx - mw / 2) / (mw * 0.6)) ** 2 + ((yy - mh / 2) / (mh * 0.6)) ** 2)
        mask = np.clip(1.0 - d, 0, 1)[..., None]
        roi = rgb[y0:y1, x0:x1].astype(np.float32)
        over = np.clip(roi - KNEE, 0, None)
        compressed = roi - over * 0.55  # 하이라이트만 눌러 톤 복원
        rgb[y0:y1, x0:x1] = np.clip(
            roi * (1 - mask) + compressed * mask, 0, 255).astype(np.uint8)
        n += 1
    return n


def process(r):
    img, _m = previews.arw_fallback(r["path"])
    if img is None:
        return (r["filename"], "실패")
    rgb = np.asarray(img.convert("RGB")).copy()
    # 노출 리프트 (근사, 리뷰용) — 단체사진은 대체로 밝아 리프트 거의 없음
    p99 = r["brightness"]
    if p99 and 0 < p99 < 0.75:
        d = math.log2(0.75 / p99)
        lift = min(3.5, 0.8 * d + 0.75 * min(1.0, d / 0.5))
        lin = (rgb.astype(np.float32) / 255.0) ** 2.2
        lin *= 2.0 ** lift
        over = lin > 0.8
        lin[over] = 0.8 + 0.2 * (1.0 - np.exp(-(lin[over] - 0.8) / 0.25))
        rgb = (np.clip(lin, 0, 1) ** (1 / 2.2) * 255.0 + 0.5).astype(np.uint8)
    hot = compress_hot_faces(rgb)
    if max(rgb.shape[:2]) > RESIZE:
        s = RESIZE / max(rgb.shape[:2])
        rgb = cv2.resize(rgb, (int(rgb.shape[1] * s), int(rgb.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    img_out = Image.fromarray(rgb)
    lo, hi, best = 60, 92, None
    while lo <= hi:
        q = (lo + hi) // 2
        buf = io.BytesIO()
        img_out.save(buf, "JPEG", quality=q, subsampling=1)
        if buf.tell() <= MAX_BYTES:
            best, lo = buf.getvalue(), q + 1
        else:
            hi = q - 1
    (OUT_DIR / (Path(r["filename"]).stem + ".jpg")).write_bytes(best)
    return (r["filename"], f"과노출얼굴 {hot}" if hot else "")


n_hot = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    for name, note in ex.map(process, targets):
        if note:
            n_hot += 1
print(f"출력 완료 {len(targets)}장 → {OUT_DIR}")
print(f"과노출 얼굴 압축 적용: {n_hot}장")
