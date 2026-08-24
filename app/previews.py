"""프리뷰 캐시 — RAW 임베디드 JPEG 추출 (풀 디코딩 없음, 장당 수십 ms).

소니 ARW는 풀사이즈에 가까운 임베디드 JPEG를 품고 있어서
rawpy.extract_thumb 로 꺼낸 뒤 두 단계로 리사이즈해 캐시한다:
  thumb   : 긴변 480px  (그리드용)
  preview : 긴변 2560px (뷰어/분석용)
"""
import hashlib
import io
from pathlib import Path

import rawpy
from PIL import Image, ImageOps

from .catalog import CACHE_ROOT

THUMB_SIZE = 480
PREVIEW_SIZE = 2560

THUMB_DIR = CACHE_ROOT / "thumbs"
PREVIEW_DIR = CACHE_ROOT / "previews"


def cache_key(path: str, mtime: float) -> str:
    return hashlib.sha1(f"{path}|{mtime}".encode("utf-8")).hexdigest()


def thumb_path(key: str) -> Path:
    return THUMB_DIR / f"{key}.jpg"


def preview_path(key: str) -> Path:
    return PREVIEW_DIR / f"{key}.jpg"


def _exif_meta(img: Image.Image) -> dict:
    """임베디드 JPEG의 EXIF에서 주요 촬영정보 추출."""
    meta = {}
    try:
        exif = img.getexif()
        if not exif:
            return meta
        ifd = exif.get_ifd(0x8769)  # ExifIFD
        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        iso = ifd.get(0x8827)
        if iso:
            meta["iso"] = int(iso if not isinstance(iso, (tuple, list)) else iso[0])
        et = num(ifd.get(0x829A))
        if et:
            meta["shutter"] = f"1/{round(1/et)}" if et < 1 else f"{et:g}s"
        fn = num(ifd.get(0x829D))
        if fn:
            meta["aperture"] = f"f/{fn:g}"
        fl = num(ifd.get(0x920A))
        if fl:
            meta["focal"] = f"{fl:g}mm"
        dt = exif.get(0x0132) or ifd.get(0x9003)
        if dt:
            meta["datetime"] = str(dt)
        model = exif.get(0x0110)
        if model:
            meta["camera"] = str(model).strip()
    except Exception:
        pass
    return meta


def arw_fallback(raw_path: str):
    """LibRaw 미지원 신기종(예: a7M5) ARW — tifffile로 풀사이즈 임베디드 JPEG·EXIF 추출.

    반환: (PIL.Image | None, meta dict)
    """
    import tifffile

    def _rat(v):
        try:
            if isinstance(v, tuple) and len(v) == 2 and v[1]:
                return v[0] / v[1]
            return float(v)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    try:
        with tifffile.TiffFile(raw_path) as t:
            meta = {}
            p0 = t.pages[0]
            model = p0.tags.get(272)
            if model:
                meta["camera"] = str(model.value).strip()
            dt = p0.tags.get(306)
            if dt:
                meta["datetime"] = str(dt.value)
            et = p0.tags.get(34665)
            if et and isinstance(et.value, dict):
                v = et.value
                iso = v.get("ISOSpeedRatings")
                if iso:
                    meta["iso"] = int(iso if not isinstance(iso, (tuple, list)) else iso[0])
                exp = _rat(v.get("ExposureTime"))
                if exp:
                    meta["shutter"] = f"1/{round(1/exp)}" if exp < 1 else f"{exp:g}s"
                fn = _rat(v.get("FNumber"))
                if fn:
                    meta["aperture"] = f"f/{fn:g}"
                fl = _rat(v.get("FocalLength"))
                if fl:
                    meta["focal"] = f"{fl:g}mm"
                if v.get("DateTimeOriginal"):
                    meta["datetime"] = str(v["DateTimeOriginal"])
            # 가장 큰 JPEG 페이지 = 풀사이즈 프리뷰
            best, best_px = None, 0
            for p in t.pages:
                if p.shape and "JPEG" in str(p.compression):
                    px = p.shape[0] * p.shape[1]
                    if px > best_px:
                        best, best_px = p, px
            if best is None:
                return None, meta
            img = Image.fromarray(best.asarray())
            ori = p0.tags.get(274)
            ori_v = int(getattr(ori.value, "value", ori.value)) if ori else 1
            if ori_v == 3:
                img = img.rotate(180, expand=True)
            elif ori_v == 6:
                img = img.rotate(-90, expand=True)
            elif ori_v == 8:
                img = img.rotate(90, expand=True)
            return img, meta
    except Exception:
        return None, {}


def build_previews(raw_path: str, key: str) -> tuple[bool, dict]:
    """임베디드 JPEG를 추출해 thumb/preview 캐시 생성. (성공여부, EXIF메타) 반환."""
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    tp, pp = thumb_path(key), preview_path(key)
    try:
        img = None
        meta = {}
        try:
            with rawpy.imread(raw_path) as raw:
                thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = Image.open(io.BytesIO(thumb.data))
            else:  # 비트맵 썸네일 (드묾)
                img = Image.fromarray(thumb.data)
            meta = _exif_meta(img)
        except rawpy.LibRawFileUnsupportedError:
            # LibRaw 미지원 신기종 → tifffile 폴백
            img, meta = arw_fallback(raw_path)
            if img is None:
                return False, meta
        if tp.exists() and pp.exists():
            return True, meta
        # 임베디드 JPEG에는 회전 EXIF가 들어있는 경우가 있어 반영
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        pv = img.copy()
        pv.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
        pv.save(pp, "JPEG", quality=88)

        img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        img.save(tp, "JPEG", quality=82)
        return True, meta
    except Exception:
        return False, {}
