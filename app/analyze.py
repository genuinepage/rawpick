"""자동 컬링 분석 — 선명도(전역/얼굴영역) 측정.

프리뷰 JPEG(긴변 2560) 기준으로 측정한다. RAW 풀디코딩 불필요.
- 전역 선명도: 고정 폭으로 리사이즈 후 라플라시안 분산 (촬영본 간 비교 가능하도록 정규화)
- 얼굴 선명도: 가장 큰 얼굴 박스 내부의 라플라시안 분산 → "배경에 핀 맞은 컷" 검출
플래그 판정은 절대값이 아니라 폴더 내 분포(중앙값) 기준 상대 판정 —
렌즈·조리개·장면이 달라도 "그 촬영에서 유독 흐린 컷"을 잡는다.
"""
import math

import cv2
import numpy as np

ANALYZE_WIDTH = 1600

_face_detector = None


def _get_face_detector():
    global _face_detector
    if _face_detector is None:
        _face_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _face_detector


def _lap_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyze_image(preview_file: str) -> dict | None:
    img = cv2.imread(preview_file, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w != ANALYZE_WIDTH:
        scale = ANALYZE_WIDTH / w
        img = cv2.resize(img, (ANALYZE_WIDTH, max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    sharpness = math.log10(max(_lap_var(gray), 1e-6))

    faces = _get_face_detector().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(48, 48))
    face_sharpness = None
    if len(faces) > 0:
        # 가장 큰 얼굴 기준
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        roi = gray[y:y + fh, x:x + fw]
        if roi.size > 0:
            face_sharpness = math.log10(max(_lap_var(roi), 1e-6))

    return {
        "sharpness": round(sharpness, 3),
        "face_count": int(len(faces)),
        "face_sharpness": round(face_sharpness, 3) if face_sharpness is not None else None,
    }


def compute_cull_flags(rows: list[dict]) -> dict[int, str]:
    """폴더 단위 분포 기반 플래그. {photo_id: flag} 반환.

    log10 스케일이므로 -0.6 = 중앙값 대비 선명도 1/4 수준.
    """
    ids_flags: dict[int, str] = {}
    sharp_vals = [r["sharpness"] for r in rows if r["sharpness"] is not None]
    if not sharp_vals:
        return ids_flags
    med = float(np.median(sharp_vals))
    face_vals = [r["face_sharpness"] for r in rows if r["face_sharpness"] is not None]
    face_med = float(np.median(face_vals)) if face_vals else None

    for r in rows:
        flag = ""
        s = r["sharpness"]
        fs = r["face_sharpness"]
        if s is not None and s < med - 0.6:
            flag = "blurry"
        elif fs is not None and face_med is not None and fs < face_med - 0.6:
            flag = "soft_face"
        ids_flags[r["id"]] = flag
    return ids_flags
