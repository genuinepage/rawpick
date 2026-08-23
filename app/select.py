"""AI 목표컷 셀렉 — CLIP 임베딩 + 미학점수 기반 자동 별점 분류.

파이프라인:
  1. CLIP ViT-B/32로 전 컷 임베딩 + LAION aesthetic 점수 (GPU, 배치)
  2. 노출 페널티 (하이라이트/섀도 클리핑 비율)
  3. 종합 점수 = 미학(주 가중치) + 선명도 + 얼굴 + 노출  — 폴더 내 백분위 정규화
  4. 연사 그룹핑: 같은 카메라·촬영시각 근접·임베딩 유사 컷을 묶고 그룹 베스트 선출
  5. 시간대 쿼터를 걸어 목표수량 선발 (특정 곡/장면에 몰림 방지)

별점 매핑 (사용자 확정):
  ★3 = 목표수량 선발컷 / ★2 = 그룹 베스트지만 목표에 못 든 차점컷
  ★1 = 불량컷 필터 통과한 나머지 / 0 = 흐림·핀아웃 플래그컷
"""
import datetime as _dt
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from .catalog import CACHE_ROOT

# ---- 가중치 (창작무용: 미학 우선, 얼굴 없는 컷 불이익 없음) ----
W_AES = 0.55
W_SHARP = 0.20
W_FACE = 0.10
W_EXPO = 0.15
W_TASTE = 0.15  # 취향 모델(사람 셀렉/탈락 학습) 보조 가중 — 모델 있을 때만 가산

SIM_THRESHOLD = 0.90   # 연사 그룹핑 코사인 유사도
TIME_GAP_SEC = 4.0     # 연사 그룹핑 최대 시각 간격
SEGMENT_MIN = 10       # 시간대 쿼터 버킷 (분)
RUNNERUP_RATIO = 0.3   # ★2 차점컷 밴드 크기 (목표수량 대비)

AES_HEAD_URL = ("https://github.com/LAION-AI/aesthetic-predictor/raw/main/"
                "sa_0_4_vit_b_32_linear.pth")
MODEL_DIR = CACHE_ROOT / "models"

_clip = None  # (model, preprocess, aes_head, device)


def _load_models():
    global _clip
    if _clip is not None:
        return _clip
    import torch
    import open_clip
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai", cache_dir=str(MODEL_DIR))
    model = model.to(device).eval()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    head_path = MODEL_DIR / "sa_0_4_vit_b_32_linear.pth"
    if not head_path.exists():
        urllib.request.urlretrieve(AES_HEAD_URL, head_path)
    aes_head = torch.nn.Linear(512, 1)
    aes_head.load_state_dict(torch.load(head_path, map_location="cpu"))
    aes_head = aes_head.to(device).eval()
    _clip = (model, preprocess, aes_head, device)
    return _clip


def embed_and_score(image_paths: list[str], progress_cb=None,
                    batch_size: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """이미지 목록 → (임베딩 [N,512] 정규화, 미학점수 [N]). 실패한 이미지는 0벡터/NaN."""
    import torch
    model, preprocess, aes_head, device = _load_models()
    N = len(image_paths)
    embs = np.zeros((N, 512), dtype=np.float32)
    scores = np.full(N, np.nan, dtype=np.float32)
    with torch.no_grad():
        for start in range(0, N, batch_size):
            chunk = image_paths[start:start + batch_size]
            tensors, idxs = [], []
            for i, p in enumerate(chunk):
                try:
                    img = Image.open(p).convert("RGB")
                    tensors.append(preprocess(img))
                    idxs.append(start + i)
                except Exception:
                    pass
            if not tensors:
                continue
            batch = torch.stack(tensors).to(device)
            feat = model.encode_image(batch)
            feat = feat / feat.norm(dim=-1, keepdim=True)
            aes = aes_head(feat.float()).squeeze(-1)
            embs[idxs] = feat.float().cpu().numpy()
            scores[idxs] = aes.cpu().numpy()
            if progress_cb:
                progress_cb(min(start + batch_size, N), N)
    return embs, scores


def exposure_penalty(thumb_file: str) -> float:
    """클리핑 비율 기반 노출 페널티 0(좋음)~1(나쁨). 무대조명 특성상 관대하게."""
    try:
        img = Image.open(thumb_file).convert("L")
        h = np.asarray(img.histogram(), dtype=np.float64)
        total = h.sum()
        if total == 0:
            return 0.0
        hi_clip = h[252:].sum() / total   # 완전 날아간 하이라이트
        lo_clip = h[:3].sum() / total     # 완전 뭉개진 섀도 (무대 암전은 흔하므로 약하게)
        return float(min(1.0, hi_clip * 4 + lo_clip * 1.0))
    except Exception:
        return 0.0


def _percentile_norm(vals: np.ndarray) -> np.ndarray:
    """NaN 무시 백분위 정규화 → 0~1. NaN은 0.5(중립)."""
    out = np.full(len(vals), 0.5, dtype=np.float32)
    mask = ~np.isnan(vals)
    if mask.sum() >= 2:
        ranks = vals[mask].argsort().argsort().astype(np.float32)
        out[mask] = ranks / max(1, mask.sum() - 1)
    return out


def _parse_dt(meta: dict, fallback_mtime: float) -> float:
    dt = meta.get("datetime")
    if dt:
        try:
            return _dt.datetime.strptime(dt, "%Y:%m:%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    return fallback_mtime


def run_selection(rows: list[dict], embs: np.ndarray, aes: np.ndarray,
                  expo: np.ndarray, target: int) -> dict:
    """종합점수·그룹핑·쿼터 선발. rows 순서와 embs/aes/expo 인덱스는 동일해야 함.

    반환: {"quality": [N], "picks": {photo_id: 1|2|3}, "stats": {...}}
    """
    N = len(rows)
    sharp = np.array([r["sharpness"] if r["sharpness"] is not None else np.nan
                      for r in rows], dtype=np.float32)
    fsharp = np.array([r["face_sharpness"] if r["face_sharpness"] is not None else np.nan
                       for r in rows], dtype=np.float32)

    aes_n = _percentile_norm(aes)
    sharp_n = _percentile_norm(sharp)
    face_n = _percentile_norm(fsharp)      # 얼굴 없으면 0.5 중립
    expo_n = 1.0 - np.clip(expo, 0, 1)

    quality = W_AES * aes_n + W_SHARP * sharp_n + W_FACE * face_n + W_EXPO * expo_n

    # 취향 모델 (scripts/train_taste.py 로 학습된 개인화 점수)
    taste_path = MODEL_DIR / "taste_head.npz"
    if taste_path.exists() and embs is not None and len(embs) == N:
        t = np.load(taste_path)
        logits = embs @ t["w"] + float(t["b"])
        taste_n = _percentile_norm(1.0 / (1.0 + np.exp(-logits)))
        quality = quality + W_TASTE * taste_n

    # ---- 연사 그룹핑 (카메라별 → 시각순 → 인접 유사컷 병합) ----
    times = np.array([_parse_dt(r["meta"], r["mtime"]) for r in rows])
    cams = [r["meta"].get("camera", "") for r in rows]
    clean = [i for i, r in enumerate(rows) if not r["cull_flag"]]

    groups: list[list[int]] = []
    for cam in sorted(set(cams[i] for i in clean)):
        idxs = sorted((i for i in clean if cams[i] == cam), key=lambda i: (times[i], rows[i]["filename"]))
        cur: list[int] = []
        for i in idxs:
            if cur:
                j = cur[-1]
                sim = float(embs[i] @ embs[j])
                if times[i] - times[j] <= TIME_GAP_SEC and sim >= SIM_THRESHOLD:
                    cur.append(i)
                    continue
                groups.append(cur)
            cur = [i]
        if cur:
            groups.append(cur)

    # 그룹 베스트 (quality 최고)
    bests = [max(g, key=lambda i: quality[i]) for g in groups]

    # ---- 시간대 쿼터 선발 ----
    picks: dict[int, int] = {}
    target = max(0, min(target, len(clean)))
    if bests:
        seg_of = {}
        t0 = min(times[i] for i in bests)
        for i in bests:
            seg_of[i] = int((times[i] - t0) // (SEGMENT_MIN * 60))
        segments: dict[int, list[int]] = {}
        for i in bests:
            segments.setdefault(seg_of[i], []).append(i)
        for s in segments:
            segments[s].sort(key=lambda i: -quality[i])

        pool = len(bests)
        chosen: list[int] = []
        n_target_from_bests = min(target, pool)
        # 쿼터: 세그먼트 풀 크기 비례 배분 + 최소 1장 보장
        alloc = {s: max(1, round(n_target_from_bests * len(v) / pool))
                 for s, v in segments.items()}
        for s, v in segments.items():
            chosen.extend(v[:alloc[s]])
        # 배분 오차 보정: 초과분은 점수 낮은 것부터 제외, 부족분은 미선발 베스트에서 점수순 충원
        chosen.sort(key=lambda i: -quality[i])
        chosen = chosen[:n_target_from_bests]
        rest_bests = sorted(set(bests) - set(chosen), key=lambda i: -quality[i])
        while len(chosen) < n_target_from_bests and rest_bests:
            chosen.append(rest_bests.pop(0))

        for i in chosen:
            picks[rows[i]["id"]] = 3

        # 그룹 베스트 수가 목표보다 적으면 2순위 컷에서 점수순 충원
        if len(chosen) < target:
            seconds = sorted((i for i in clean if rows[i]["id"] not in picks),
                             key=lambda i: -quality[i])
            fill = seconds[:target - len(chosen)]
            for i in fill:
                picks[rows[i]["id"]] = 3

        # ★2 차점컷: 목표 밖 그룹 베스트 + 남은 컷 중 품질 상위 밴드 (목표의 30%)
        runnerup_n = max(len(rest_bests), round(target * RUNNERUP_RATIO))
        rest_best_set = set(rest_bests)
        runners = sorted((i for i in clean if rows[i]["id"] not in picks),
                         key=lambda i: (i not in rest_best_set, -quality[i]))
        for i in runners[:runnerup_n]:
            picks[rows[i]["id"]] = 2

    for i in clean:
        picks.setdefault(rows[i]["id"], 1)

    n3 = sum(1 for v in picks.values() if v == 3)
    n2 = sum(1 for v in picks.values() if v == 2)
    n1 = sum(1 for v in picks.values() if v == 1)
    return {
        "quality": quality,
        "picks": picks,
        "stats": {"total": N, "clean": len(clean), "groups": len(groups),
                  "star3": n3, "star2": n2, "star1": n1,
                  "flagged": N - len(clean)},
    }
