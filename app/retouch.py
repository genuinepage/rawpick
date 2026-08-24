"""보수적 인물 보정 — 피부 정돈(주파수 분리) + 미세 턱선 슬리밍.

설계 원칙 (사용자 확정):
- 파이프라인 기본은 "사진이 안정돼 보이는" 약한 수준 고정. 강한 보정은 포토샵/이보토 몫.
- 살결(고주파 질감)은 보존하고 잡티·요철(중간주파)만 정리 — 뭉개짐 방지.
- 얼굴형은 픽셀 재생성 없이 기하 워핑(리퀴파이 원리)만, 얼굴폭의 1% 미만.
- 게이팅: 작은 얼굴은 피부 스킵, 측면·저신뢰 얼굴은 워핑 스킵. 안 되는 컷은 안 건드림.

모델: MediaPipe FaceLandmarker (~/.rawpick/models/face_landmarker.task)
"""
import threading

import cv2
import numpy as np

from .catalog import CACHE_ROOT

MODEL_PATH = CACHE_ROOT / "models" / "face_landmarker.task"
YUNET_PATH = CACHE_ROOT / "models" / "face_detection_yunet_2023mar.onnx"

# 기본 강도 (약한 수준 고정)
SKIN_BLEND = 0.40       # 피부 정돈 블렌딩 (사용자 확정: 25%→40% 1단계 상향)
JAW_SLIM = 0.007        # 턱선 이동량 (얼굴폭 비율)
MIN_FACE_SKIN = 140     # 피부 정돈 최소 얼굴 높이(px)
MIN_FACE_RESHAPE = 300  # 턱선 보정 최소 얼굴 높이(px)

# FaceMesh 랜드마크 인덱스
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365,
             379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93,
             234, 127, 162, 21, 54, 103, 67, 109]
JAWLINE = [58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288]
LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
RIGHT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
LEFT_BROW = [70, 63, 105, 66, 107]
RIGHT_BROW = [336, 296, 334, 293, 300]

_lock = threading.Lock()
_landmarker = None


def available() -> bool:
    return MODEL_PATH.exists() and YUNET_PATH.exists()


_yunet = None


def _find_face_boxes(rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
    """YuNet으로 얼굴 박스 검출 (무대 거리 소형 얼굴 대응). 원본 좌표 (x,y,w,h)."""
    global _yunet
    h, w = rgb.shape[:2]
    scale = min(1.0, 1600.0 / w)
    dw, dh = int(w * scale), int(h * scale)
    if _yunet is None:
        _yunet = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (dw, dh),
                                           score_threshold=0.6)
    _yunet.setInputSize((dw, dh))
    small = cv2.resize(rgb, (dw, dh), interpolation=cv2.INTER_AREA)
    _, dets = _yunet.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    boxes = []
    if dets is not None:
        for d in dets:
            x, y, bw, bh = d[:4] / scale
            boxes.append((float(x), float(y), float(bw), float(bh)))
    return boxes


def _get_landmarker():
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        opts = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_faces=8, min_face_detection_confidence=0.4,
            output_facial_transformation_matrixes=True)
        _landmarker = vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def _detect(rgb: np.ndarray):
    """2단 검출: YuNet 박스(소형 얼굴 OK) → 얼굴 크롭에서 랜드마크 정밀 검출."""
    import mediapipe as mp
    h, w = rgb.shape[:2]
    faces = []
    for (bx, by, bw, bh) in _find_face_boxes(rgb):
        # 랜드마크는 여유 크롭(2배)에서 — 크롭이라 얼굴이 커져 검출 안정
        cx, cy = bx + bw / 2, by + bh / 2
        half = max(bw, bh)
        x0, y0 = max(0, int(cx - half)), max(0, int(cy - half))
        x1, y1 = min(w, int(cx + half)), min(h, int(cy + half))
        chip = rgb[y0:y1, x0:x1]
        if chip.shape[0] < 32 or chip.shape[1] < 32:
            continue
        cscale = 512.0 / max(chip.shape[:2])
        chip_s = cv2.resize(chip, (max(1, int(chip.shape[1] * cscale)),
                                   max(1, int(chip.shape[0] * cscale))))
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.ascontiguousarray(chip_s))
        with _lock:
            res = _get_landmarker().detect(img)
        if not res.face_landmarks:
            continue
        lms = res.face_landmarks[0]
        pts = np.array([[p.x * chip_s.shape[1] / cscale + x0,
                         p.y * chip_s.shape[0] / cscale + y0]
                        for p in lms], dtype=np.float32)
        yaw = None
        if res.facial_transformation_matrixes:
            m = np.array(res.facial_transformation_matrixes[0])
            # 회전행렬에서 yaw 추출
            yaw = abs(math_degrees_asin(-m[2, 0]))
        faces.append((pts, yaw))
    return faces


def math_degrees_asin(v: float) -> float:
    import math
    return math.degrees(math.asin(max(-1.0, min(1.0, float(v)))))


def _skin_mask(shape, pts) -> np.ndarray:
    """얼굴 윤곽 - (눈·눈썹·입술) 마스크, 가장자리 페더링."""
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [pts[FACE_OVAL].astype(np.int32)], 255)
    for idxs in (LEFT_EYE, RIGHT_EYE, LIPS):
        hull = cv2.convexHull(pts[idxs].astype(np.int32))
        cv2.fillPoly(mask, [cv2.convexHull(
            ((hull - hull.mean(0)) * 1.35 + hull.mean(0)).astype(np.int32))], 0)
    for idxs in (LEFT_BROW, RIGHT_BROW):
        cv2.fillPoly(mask, [cv2.convexHull(pts[idxs].astype(np.int32))], 0)
    face_h = np.ptp(pts[FACE_OVAL][:, 1])
    k = max(3, int(face_h * 0.04) | 1)
    mask = cv2.GaussianBlur(mask, (k, k), 0)
    return mask.astype(np.float32) / 255.0


def _smooth_skin(rgb: np.ndarray, pts, blend: float) -> np.ndarray:
    """주파수 분리: 중간주파(잡티·요철)만 정리, 고주파(살결)·저주파(입체감) 보존."""
    x0, y0 = pts[FACE_OVAL].min(0) - 20
    x1, y1 = pts[FACE_OVAL].max(0) + 20
    h, w = rgb.shape[:2]
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return rgb
    roi = rgb[y0:y1, x0:x1].astype(np.float32)
    face_h = np.ptp(pts[FACE_OVAL][:, 1])
    r_mid = max(3, int(face_h * 0.02)) | 1     # 잡티 대역
    r_fine = max(1, int(face_h * 0.006)) | 1   # 살결 보존 대역
    low = cv2.GaussianBlur(roi, (0, 0), r_mid)
    fine = roi - cv2.GaussianBlur(roi, (0, 0), r_fine)
    smooth = np.clip(low + fine, 0, 255)
    m = _skin_mask(rgb.shape, pts)[y0:y1, x0:x1][..., None] * blend
    out = rgb.copy()
    out[y0:y1, x0:x1] = (roi * (1 - m) + smooth * m).astype(np.uint8)
    return out


def _frontal_enough(pts) -> bool:
    """측면 얼굴 제외 — 코 기준 좌우 볼 폭 비율."""
    nose_x = pts[4][0]
    left = abs(nose_x - pts[234][0])
    right = abs(pts[454][0] - nose_x)
    if min(left, right) < 1:
        return False
    ratio = left / right
    return 0.55 <= ratio <= 1.8


def _slim_jaw(rgb: np.ndarray, pts, k: float) -> np.ndarray:
    """턱선 포인트를 얼굴 중심축 쪽으로 미세 이동 (TPS 워핑, ROI 한정)."""
    oval = pts[FACE_OVAL]
    face_w = np.ptp(oval[:, 0])
    cx = oval[:, 0].mean()
    pad = int(face_w * 0.9)
    x0 = max(0, int(oval[:, 0].min()) - pad)
    y0 = max(0, int(oval[:, 1].min()) - pad)
    x1 = min(rgb.shape[1], int(oval[:, 0].max()) + pad)
    y1 = min(rgb.shape[0], int(oval[:, 1].max()) + pad)
    roi = rgb[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rh < 40 or rw < 40:
        return rgb

    # 가우시안 변위장: 턱선 포인트 주변만 국소적으로 안쪽으로 밀기.
    # (TPS warpImage는 불안정해 이미지가 깨지는 사례가 있어 명시적 리맵으로 대체)
    sigma = face_w * 0.16
    acc_dx = np.zeros((rh, rw), dtype=np.float32)
    acc_w = np.zeros((rh, rw), dtype=np.float32)
    yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float32)
    for i in JAWLINE:
        x, y = pts[i]
        lx, ly = x - x0, y - y0
        dx = (cx - x) * k * 2.0
        w_map = np.exp(-((xx - lx) ** 2 + (yy - ly) ** 2) / (2 * sigma * sigma))
        acc_dx += w_map * dx
        acc_w += w_map
    flow_x = acc_dx / np.maximum(acc_w, 1.0)  # 겹침 평균 (앵커 불필요, 멀면 자연 감쇠)
    map_x = xx - flow_x.astype(np.float32)    # 역방향 샘플링 (소변위 근사)
    map_y = yy
    warped = cv2.remap(roi, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out = rgb.copy()
    out[y0:y1, x0:x1] = warped
    return out


def retouch(rgb: np.ndarray, skin: bool = True, reshape: bool = True,
            skin_blend: float = SKIN_BLEND, jaw_k: float = JAW_SLIM) -> tuple[np.ndarray, dict]:
    """보수적 인물 보정. (결과, 통계) 반환. 조건 미달 얼굴은 그대로 둔다."""
    stats = {"faces": 0, "skin": 0, "reshape": 0}
    if not available():
        return rgb, stats
    faces = _detect(rgb)
    stats["faces"] = len(faces)
    out = rgb
    for pts, yaw in faces:
        face_h = float(np.ptp(pts[FACE_OVAL][:, 1]))
        if skin and face_h >= MIN_FACE_SKIN:
            out = _smooth_skin(out, pts, skin_blend)
            stats["skin"] += 1
        frontal = (yaw is not None and yaw <= 20.0) or (yaw is None and _frontal_enough(pts))
        if reshape and face_h >= MIN_FACE_RESHAPE and frontal:
            out = _slim_jaw(out, pts, jaw_k)
            stats["reshape"] += 1
    return out, stats

