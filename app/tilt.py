"""수평 기울기 감지·보정.

무대 바닥선·세트 모서리 등 수평 계열의 긴 직선을 Hough로 찾아
길이 가중 중앙값으로 기울기를 추정한다.

보정 대상 판정 (detect_tilt 사용처의 규칙):
  |tilt| 0.3°~3.0° + 라인 신뢰도 충분 → 미세 실수 기울기로 보고 보정
  3° 초과 → 의도적 더치앵글로 간주, 제외
  기준선이 안 잡히면(신뢰도 부족) None → 제외
"""
import math

import cv2
import numpy as np

DETECT_WIDTH = 1600
MAX_LINE_ANGLE = 8.0      # 수평 후보로 볼 최대 기울기(도)
MIN_CONF_FRAC = 0.5       # 인라이어 라인 길이 합 최소 (이미지 폭 대비)

CORRECT_MIN = 0.3         # 보정 최소각
CORRECT_MAX = 5.0         # 보정 최대각 (사용자 확정: 적극 보정, 초과만 의도적 간주)


def detect_tilt(preview_file: str) -> float | None:
    """수평 기울기(도) 추정. 기준선이 불충분하면 None.

    v2: CLAHE 대비 정규화로 어두운 무대 바닥선도 검출 + 하단부(바닥선·반사 경계)
    가중 + 짧은 선분 누적 집계. 검출 실패 컷은 장면 단위 전파로 보완한다.
    """
    img = cv2.imread(preview_file, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape
    if w != DETECT_WIDTH:
        s = DETECT_WIDTH / w
        img = cv2.resize(img, (DETECT_WIDTH, max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)
        h, w = img.shape
    img = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(img)
    edges = cv2.Canny(img, 30, 90)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                            minLineLength=int(w * 0.12), maxLineGap=12)
    if lines is None:
        return None
    cands = []  # (angle, weight)
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            continue
        ang = math.degrees(math.atan2(dy, dx))
        if ang > 90:
            ang -= 180
        elif ang < -90:
            ang += 180
        if abs(ang) > MAX_LINE_ANGLE:
            continue
        weight = length ** 1.5  # 긴 선 우대
        if max(y1, y2) > h * 0.45:  # 하단부(바닥선 영역) 가중
            weight *= 2.0
        cands.append((ang, weight))
    if not cands:
        return None
    # 가중 중앙값
    cands.sort(key=lambda c: c[0])
    total = sum(c[1] for c in cands)
    acc = 0.0
    med = cands[0][0]
    for ang, weight in cands:
        acc += weight
        if acc >= total / 2:
            med = ang
            break
    # 신뢰도: 중앙값 ±0.5° 인라이어 가중 합이 전체의 40% 이상 + 절대량 확보
    inlier = sum(wt for ang, wt in cands if abs(ang - med) <= 0.5)
    if inlier < total * 0.4 or inlier < (w * 0.35) ** 1.5:
        return None
    return round(med, 2)


def correction_angle(tilt: float | None) -> float:
    """보정할 회전각(도). 대상이 아니면 0."""
    if tilt is None:
        return 0.0
    if CORRECT_MIN <= abs(tilt) <= CORRECT_MAX:
        return -tilt
    return 0.0


def _max_inscribed(w: int, h: int, angle_deg: float) -> tuple[int, int]:
    """회전 후 검은 모서리 없는 최대 내접 사각형 (원본 종횡비 유지 아님, 축 정렬)."""
    a = math.radians(abs(angle_deg))
    if w <= 0 or h <= 0:
        return w, h
    width_is_longer = w >= h
    side_long, side_short = (w, h) if width_is_longer else (h, w)
    sin_a, cos_a = abs(math.sin(a)), abs(math.cos(a))
    if side_short <= 2.0 * sin_a * cos_a * side_long or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * side_short
        wr, hr = (x / sin_a, x / cos_a) if width_is_longer else (x / cos_a, x / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        wr = (w * cos_a - h * sin_a) / cos_2a
        hr = (h * cos_a - w * sin_a) / cos_2a
    return int(wr), int(hr)


def rotate_level(rgb: np.ndarray, angle_deg: float) -> np.ndarray:
    """이미지를 회전해 수평을 맞추고 모서리 없는 영역으로 크롭."""
    h, w = rgb.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    rot = cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_LANCZOS4)
    cw, ch = _max_inscribed(w, h, angle_deg)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return rot[y0:y0 + ch, x0:x0 + cw]
