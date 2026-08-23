"""SCUNet AI 디노이즈 — 고노이즈 컷(실효 ISO 8000↑)용.

24MP 풀해상도를 512px 타일(32px 오버랩)로 나눠 GPU 추론 (RTX 3090 기준 장당 ~21초).
내보내기 워커가 멀티스레드라 GPU 추론은 전역 락으로 직렬화한다.
모델: scunet_color_real_psnr (실사 노이즈 학습) — ~/.rawpick/models/
"""
import sys
import threading
from pathlib import Path

import numpy as np

from .catalog import CACHE_ROOT

SCUNET_DIR = Path(__file__).parent.parent / "third_party" / "SCUNet"
WEIGHTS = CACHE_ROOT / "models" / "scunet_color_real_psnr.pth"
TILE, OVERLAP = 512, 32

_lock = threading.Lock()
_model = None


def available() -> bool:
    return WEIGHTS.exists() and SCUNET_DIR.exists()


def _get_model():
    global _model
    if _model is None:
        import torch
        if str(SCUNET_DIR) not in sys.path:
            sys.path.insert(0, str(SCUNET_DIR))
        from models.network_scunet import SCUNet
        m = SCUNet(in_nc=3, config=[4, 4, 4, 4, 4, 4, 4], dim=64)
        m.load_state_dict(torch.load(WEIGHTS, map_location="cpu"), strict=True)
        if torch.cuda.is_available():
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"  # 애플실리콘
        else:
            device = "cpu"
        _model = (m.to(device).eval(), device)
    return _model


BATCH = 8  # 타일 배치 크기 (GPU 활용률 확보)


def denoise_rgb(rgb: np.ndarray) -> np.ndarray:
    """uint8 RGB 전체 이미지 AI 디노이즈. GPU 직렬화 + fp16 + 타일 배치."""
    import torch
    with _lock:
        model, device = _get_model()
        img = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1)
        _, H, W = img.shape
        out = torch.zeros_like(img)
        weight = torch.zeros(1, H, W)
        step = TILE - 2 * OVERLAP
        ys = sorted(set(list(range(0, max(1, H - TILE + 1), step)) + [max(0, H - TILE)]))
        xs = sorted(set(list(range(0, max(1, W - TILE + 1), step)) + [max(0, W - TILE)]))
        coords = [(y, x) for y in ys for x in xs]
        use_amp = device in ("cuda", "mps")
        with torch.no_grad():
            for i in range(0, len(coords), BATCH):
                chunk = coords[i:i + BATCH]
                tiles = torch.stack([img[:, y:y + TILE, x:x + TILE] for y, x in chunk]).to(device)
                with torch.autocast(device if device != "cpu" else "cpu",
                                    dtype=torch.float16, enabled=use_amp):
                    preds = model(tiles)
                preds = preds.float().cpu().clamp(0, 1)
                for (y, x), pred in zip(chunk, preds):
                    out[:, y:y + TILE, x:x + TILE] += pred
                    weight[:, y:y + TILE, x:x + TILE] += 1.0
        out = out / weight
        return (out.permute(1, 2, 0).numpy() * 255.0 + 0.5).astype(np.uint8)
