"""JPEG 내보내기.

mode="raw" (기본): LibRaw 풀디코드 → 품질 이진탐색으로 목표 용량 이하 JPEG.
  카메라 WB 유지, 자동밝기 끔(노출 보존), sRGB 8bit. EXIF는 임베디드 JPEG에서
  이식하되 Orientation은 1로 리셋(디코드 시 이미 회전 적용됨).
mode="embedded": 카메라 내장 풀사이즈 JPEG 그대로 (초고속·소니 컬러 보존이지만
  a9M3 기준 1.4MB 수준으로 압축돼 있어 화질 상한이 낮다).
"""
import io
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _tone_lut(midtone_gamma: float = 0.86, contrast: float = 0.15,
              pivot: float = 0.30, black_point: float = 0.0) -> np.ndarray:
    """어두운 컷용 톤 커브 LUT (uint8).

    1) 블랙포인트 재고정: 리프트로 떠오른 암부 바닥(뿌연 노이즈층)을 다시 0으로.
       리프트가 클수록 강하게 — 검은 무대 복원 + 암부 노이즈 침강.
    2) 미드톤 리프트: x^gamma (감마<1 → 피부 밝기 구간 상승, 양끝 고정)
    3) 약한 S-커브: 상단은 살짝 상승, 연출 어두움 보존.
    """
    x = np.linspace(0.0, 1.0, 256)
    y = x ** midtone_gamma
    y = y + contrast * (y - pivot) * 4.0 * y * (1.0 - y)
    if black_point > 0:
        y = np.clip((y - black_point) / (1.0 - black_point), 0.0, 1.0)
    return (np.clip(y, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _exif_bytes_reset_orientation(exif_data: bytes) -> bytes | None:
    try:
        ex = Image.Exif()
        ex.load(exif_data)
        ex[274] = 1  # Orientation
        return ex.tobytes()
    except Exception:
        return None


def _save_under(img: Image.Image, max_bytes: int, exif: bytes | None) -> bytes:
    """품질 이진탐색(60~95)으로 max_bytes 이하 JPEG 인코딩."""
    lo, hi, best = 60, 95, None
    while lo <= hi:
        q = (lo + hi) // 2
        buf = io.BytesIO()
        kwargs = {"quality": q, "subsampling": 1, "optimize": True}
        if exif:
            kwargs["exif"] = exif
        img.save(buf, "JPEG", **kwargs)
        if buf.tell() <= max_bytes:
            best, lo = buf.getvalue(), q + 1
        else:
            hi = q - 1
    if best is None:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=60, subsampling=1, optimize=True,
                 **({"exif": exif} if exif else {}))
        best = buf.getvalue()
    return best


def _denoise(rgb: np.ndarray, nr_level: int) -> np.ndarray:
    """단계별 후처리 NR (FBDD 이후).

    3: 크로마 median 9
    4: 크로마 median 11 + 휘도 바이래터럴(약) — 엣지 보존형이라 디테일 유지
    5: 크로마 median 13 + 휘도 바이래터럴(강)
    """
    import cv2
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    # 크로마: median 후 gaussian 추가로 색얼룩 잔여물까지 정리 (v2에서 강화)
    chroma_k = {2: 9, 3: 11, 4: 13}.get(nr_level, 15)
    for c in (1, 2):
        ch = cv2.medianBlur(ycrcb[:, :, c], chroma_k)
        ycrcb[:, :, c] = cv2.GaussianBlur(ch, (0, 0), 2.0)
    if nr_level >= 3:
        y = ycrcb[:, :, 0]
        if nr_level >= 5:
            y = cv2.bilateralFilter(y, 9, 50, 9)
        elif nr_level >= 4:
            y = cv2.bilateralFilter(y, 7, 35, 7)
        else:
            y = cv2.bilateralFilter(y, 5, 22, 5)
        ycrcb[:, :, 0] = y
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2RGB)


def export_jpeg(raw_path: str, out_path: Path, max_mb: float,
                mode: str = "raw", lift_ev: float = 0.0,
                mid_gamma: float = 1.0, nr_level: int = 0,
                rotate_deg: float = 0.0,
                texture_target: float | None = None,
                resize_long: int = 0,
                retouch_mode: str = "off") -> dict:  # off | skin | full
    max_bytes = int(max_mb * 1024 * 1024)
    try:
        raw_ctx = rawpy.imread(raw_path)
    except rawpy.LibRawFileUnsupportedError:
        raw_ctx = None
    if raw_ctx is None:
        # LibRaw 미지원 신기종 폴백: 임베디드 풀사이즈 JPEG + 근사 노출 보정
        # (리뷰용. 최종 고품질 출력은 DNG 변환 후 정식 경로로)
        from . import previews as _pv
        img, _m = _pv.arw_fallback(raw_path)
        if img is None:
            raise RuntimeError("RAW 디코드 불가 (LibRaw 미지원 + 임베디드 추출 실패)")
        rgb = np.asarray(img.convert("RGB"))
        if lift_ev > 0.01:
            lin = (rgb.astype(np.float32) / 255.0) ** 2.2
            lin *= 2.0 ** lift_ev
            over = lin > 0.8  # 부드러운 숄더로 하이라이트 보호
            lin[over] = 0.8 + 0.2 * (1.0 - np.exp(-(lin[over] - 0.8) / 0.25))
            rgb = (np.clip(lin, 0, 1) ** (1 / 2.2) * 255.0 + 0.5).astype(np.uint8)
        black_point = min(0.10, 0.035 * lift_ev)
        if mid_gamma < 0.995 or black_point > 0.005:
            rgb = _tone_lut(mid_gamma, black_point=black_point)[rgb]
        if resize_long > 0 and max(rgb.shape[:2]) > resize_long:
            import cv2
            s = resize_long / max(rgb.shape[:2])
            rgb = cv2.resize(rgb, (max(1, int(rgb.shape[1] * s)),
                                   max(1, int(rgb.shape[0] * s))),
                             interpolation=cv2.INTER_AREA)
        data = _save_under(Image.fromarray(rgb), max_bytes, None)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return {"size": len(data), "recompressed": True}

    with raw_ctx as raw:
        try:
            thumb = raw.extract_thumb()
            embedded = thumb.data if thumb.format == rawpy.ThumbFormat.JPEG else None
        except Exception:
            embedded = None

        if mode == "embedded":
            if embedded is None:
                raise RuntimeError("임베디드 JPEG 없음")
            data = embedded
            recompressed = False
            if len(data) > max_bytes:
                img = Image.open(io.BytesIO(data))
                data = _save_under(img, max_bytes, img.info.get("exif"))
                recompressed = True
        else:
            pp = {"use_camera_wb": True, "no_auto_bright": True, "output_bps": 8}
            if lift_ev > 0.01:
                # 리니어 노출 리프트 + 하이라이트 보존 (LibRaw exp_shift)
                pp["exp_shift"] = float(min(8.0, 2.0 ** lift_ev))
                pp["exp_preserve_highlights"] = 0.9
            use_ai = False
            if nr_level >= 1:  # 실효 ISO 3200↑ → AI 디노이즈 (전 구간 균일화, 사용자 확정)
                from . import ai_denoise
                use_ai = ai_denoise.available()
            if not use_ai:
                if nr_level >= 2:
                    pp["fbdd_noise_reduction"] = rawpy.FBDDNoiseReductionMode.Full
                elif nr_level == 1:
                    pp["fbdd_noise_reduction"] = rawpy.FBDDNoiseReductionMode.Light
            rgb = raw.postprocess(**pp)
            if use_ai:
                from . import ai_denoise, texture
                orig = rgb
                rgb = ai_denoise.denoise_rgb(rgb)
                # 질감 복원: 피부 가중 디테일 리인젝션 + 레퍼런스 매칭 그레인
                rgb = texture.restore(rgb, orig, texture_target)
            elif nr_level >= 2:
                rgb = _denoise(rgb, nr_level)
            if abs(rotate_deg) >= 0.05:
                from .tilt import rotate_level
                rgb = rotate_level(rgb, rotate_deg)
            if retouch_mode in ("skin", "full"):
                from . import retouch as rt
                if rt.available():
                    rgb, _st = rt.retouch(rgb, skin=True,
                                          reshape=(retouch_mode == "full"))
            # 블랙포인트: 리프트량 비례로 암부 바닥을 재고정 (뿌연 암부 방지)
            black_point = min(0.10, 0.035 * lift_ev)
            if mid_gamma < 0.995 or black_point > 0.005:
                rgb = _tone_lut(mid_gamma, black_point=black_point)[rgb]
            if resize_long > 0 and max(rgb.shape[:2]) > resize_long:
                import cv2
                s = resize_long / max(rgb.shape[:2])
                rgb = cv2.resize(rgb, (max(1, int(rgb.shape[1] * s)),
                                       max(1, int(rgb.shape[0] * s))),
                                 interpolation=cv2.INTER_AREA)
            img = Image.fromarray(rgb)
            exif = None
            if embedded:
                src_exif = Image.open(io.BytesIO(embedded)).info.get("exif")
                if src_exif:
                    exif = _exif_bytes_reset_orientation(src_exif)
            data = _save_under(img, max_bytes, exif)
            recompressed = True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"size": len(data), "recompressed": recompressed}
