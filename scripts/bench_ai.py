"""AI 디노이즈 벤치마크 — RAW 파일 불필요, 어느 플랫폼에서나 실행 가능.

24MP(6012x4020) 합성 노이즈 이미지를 만들어 SCUNet 추론 시간을 측정한다.
사용: uv run --no-sync python scripts/bench_ai.py
기준치: RTX 3090 fp16 = 장당 약 10.4초
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai_denoise  # noqa: E402

if not ai_denoise.available():
    raise SystemExit("SCUNet 미설치 — README의 세팅(third_party 클론 + 가중치 다운로드) 먼저")

rng = np.random.default_rng(0)
base = np.linspace(0, 80, 6012, dtype=np.float32)[None, :, None]
img = np.clip(base + rng.normal(0, 12, (4020, 6012, 3)), 0, 255).astype(np.uint8)

t0 = time.time()
ai_denoise.denoise_rgb(img)
t_first = time.time() - t0
t0 = time.time()
ai_denoise.denoise_rgb(img)
t_second = time.time() - t0

import torch
dev = "cuda" if torch.cuda.is_available() else (
    "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
    else "cpu")
print(f"디바이스: {dev}")
print(f"1회차(모델 로드 포함): {t_first:.1f}초 / 2회차(순수 추론): {t_second:.1f}초")
print(f"RTX 3090 대비: {t_second / 10.4:.1f}배 느림 (기준 10.4초)")
