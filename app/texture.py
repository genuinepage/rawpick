"""AI 디노이즈 후 질감 복원 (사용자 확정 설계).

- 디테일 리인젝션: 원본 고주파를 배경 15%, 피부(얼굴 랜드마크 마스크) 45%로 되섞기
  → 실제 살결·원단 질감 복원, 평탄부 노이즈 재유입 방지
- 레퍼런스 매칭 그레인: 같은 폴더의 저감도(ISO<=1000) 밝은 컷의 미세대역 에너지를
  목표로 부족분만 자동 산출 — 밝은 컷은 0, 깊이 리프트된 컷일수록 많이
- 그레인은 휘도 가중(최암부 제외)이라 검은 무대는 계속 깨끗
"""
import cv2
import numpy as np

ALPHA_BASE = 0.15
ALPHA_SKIN = 0.45
FINE_SIGMA = 1.2


def fine_std(rgb: np.ndarray) -> float:
    """미세대역(살결 주파수) 에너지 — 중간톤 영역 기준."""
    l = rgb.astype(np.float32).mean(axis=2)
    fine = l - cv2.GaussianBlur(l, (0, 0), FINE_SIGMA)
    mid = (l > 40) & (l < 190)
    return float(fine[mid].std()) if mid.any() else 0.0


def restore(den: np.ndarray, orig: np.ndarray,
            target_fine_std: float | None = None) -> np.ndarray:
    """디노이즈 결과에 원본 질감 복원. den/orig 동일 크기 uint8 RGB."""
    origf = orig.astype(np.float32)
    detail = origf - cv2.GaussianBlur(origf, (0, 0), FINE_SIGMA)

    alpha = np.full(den.shape[:2], ALPHA_BASE, dtype=np.float32)
    try:
        from . import retouch
        if retouch.available():
            for pts, _yaw in retouch._detect(orig):
                m = retouch._skin_mask(orig.shape, pts)
                alpha = np.maximum(alpha, ALPHA_BASE + (ALPHA_SKIN - ALPHA_BASE) * m)
    except Exception:
        pass  # 얼굴 검출 실패 시 전역 15%만

    out = np.clip(den.astype(np.float32) + alpha[..., None] * detail, 0, 255)

    if target_fine_std and target_fine_std > 0:
        cur = fine_std(out.astype(np.uint8))
        amp = max(0.0, target_fine_std ** 2 - cur ** 2) ** 0.5
        if amp > 0.05:
            rng = np.random.default_rng(int(den.shape[0]) * 31 + int(den.shape[1]))
            grain = cv2.GaussianBlur(
                rng.normal(0, 1.0, den.shape[:2]).astype(np.float32), (0, 0), 0.6)
            luma_w = np.clip(out.mean(axis=2) / 60.0, 0.15, 1.0)
            out = np.clip(out + (amp * grain * luma_w)[..., None], 0, 255)
    return out.astype(np.uint8)
