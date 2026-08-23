"""취향 학습 — 사람의 최종 셀렉/탈락 판단을 CLIP 임베딩으로 학습.

데이터: rating=4(확정 셀렉) vs rating=1이면서 ai_pick>=2(내보냈지만 사람이 탈락).
탈락 사유(초점·구도 애매·피사체 흔들림 등)가 임베딩 공간에서 학습된다.
모델: L2 정규화 로지스틱 회귀 (numpy, 5-fold 교차검증) → ~/.rawpick/models/taste_head.npz
다음 촬영의 AI 셀렉(quality 점수)에 개인화 항으로 반영된다.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db, CACHE_ROOT  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit("사용법: python scripts/train_taste.py <RAW 폴더 경로>")
FOLDER = str(Path(sys.argv[1]).resolve())
OUT = CACHE_ROOT / "models" / "taste_head.npz"

db = get_db()
rows = db.execute(
    "SELECT rating, ai_pick, embedding FROM photos WHERE folder=? AND embedding IS NOT NULL "
    "AND ((rating=4) OR (rating=1 AND ai_pick>=2))", (FOLDER,)).fetchall()

X, y = [], []
for r in rows:
    X.append(np.frombuffer(r["embedding"], dtype=np.float16).astype(np.float32))
    y.append(1.0 if r["rating"] == 4 else 0.0)
X = np.stack(X)
y = np.array(y, dtype=np.float32)
print(f"학습 데이터: 확정 {int(y.sum())}장 / 탈락 {int((1-y).sum())}장, 임베딩 {X.shape[1]}차원")


def train_logreg(Xtr, ytr, l2=1.0, epochs=300, lr=0.5):
    w = np.zeros(Xtr.shape[1], dtype=np.float32)
    b = 0.0
    n = len(ytr)
    # 클래스 불균형 보정
    pos_w = (1 - ytr).sum() / max(1.0, ytr.sum())
    sw = np.where(ytr == 1, pos_w, 1.0)
    for _ in range(epochs):
        z = Xtr @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        g = (p - ytr) * sw
        w -= lr * (Xtr.T @ g / n + l2 * w / n)
        b -= lr * g.mean()
    return w, b


# 5-fold 교차검증
rng = np.random.default_rng(42)
idx = rng.permutation(len(y))
folds = np.array_split(idx, 5)
accs, aucs = [], []
for k in range(5):
    te = folds[k]
    tr = np.concatenate([folds[j] for j in range(5) if j != k])
    w, b = train_logreg(X[tr], y[tr])
    p = 1.0 / (1.0 + np.exp(-(X[te] @ w + b)))
    accs.append(((p > 0.5) == (y[te] > 0.5)).mean())
    # AUC
    pos, neg = p[y[te] == 1], p[y[te] == 0]
    if len(pos) and len(neg):
        aucs.append((pos[:, None] > neg[None, :]).mean())
print(f"5-fold 정확도 {np.mean(accs)*100:.1f}% / AUC {np.mean(aucs):.3f}")

w, b = train_logreg(X, y)
np.savez(OUT, w=w, b=b)
print(f"저장: {OUT}")
