"""무대별 AI 셀렉 — 시간 간격 상위 (N-1)곳으로 무대를 나누고 무대당 목표수량 선발.

사용: python scripts/select_stages.py <RAW 폴더> <무대수> <무대당 목표수량>
별점: ★3=선발 / ★2=차점 / ★1=통과 / 0=불량플래그. XMP 동시 기록.
무대별 선발 명단은 scripts/stage_<n>.txt 저장 (리뷰용 내보내기에 사용).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db, row_to_dict  # noqa: E402
from app import previews, xmp  # noqa: E402
from app import select as sel  # noqa: E402

if len(sys.argv) < 4:
    raise SystemExit("사용법: python scripts/select_stages.py <RAW 폴더> <무대수> <무대당 목표>")
FOLDER = str(Path(sys.argv[1]).resolve())
N_STAGES = int(sys.argv[2])
TARGET = int(sys.argv[3])

db = get_db()
rows = [row_to_dict(r) for r in db.execute(
    "SELECT * FROM photos WHERE folder=? AND preview_ok=1 ORDER BY filename",
    (FOLDER,)).fetchall()]
print(f"대상 {len(rows)}장")

paths = [str(previews.preview_path(previews.cache_key(r["path"], r["mtime"]))) for r in rows]
embs, aes = sel.embed_and_score(paths)
expo = np.array([sel.exposure_penalty(
    str(previews.thumb_path(previews.cache_key(r["path"], r["mtime"]))))
    for r in rows], dtype=np.float32)

# ---- 무대 분할: 시간순 정렬 후 간격 상위 N-1 지점 ----
times = np.array([sel._parse_dt(r["meta"], r["mtime"]) for r in rows])
order = np.argsort(times, kind="stable")
sorted_t = times[order]
gaps = np.diff(sorted_t)
cut_positions = sorted(np.argsort(gaps)[-(N_STAGES - 1):]) if N_STAGES > 1 else []
stage_of = np.zeros(len(rows), dtype=int)
sid = 0
prev = 0
for cp in cut_positions:
    stage_of[order[prev:cp + 1]] = sid
    prev = cp + 1
    sid += 1
stage_of[order[prev:]] = sid

for s in range(N_STAGES):
    idxs = np.where(stage_of == s)[0]
    t0, t1 = times[idxs].min(), times[idxs].max()
    import datetime
    f = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M")
    sub_rows = [rows[i] for i in idxs]
    result = sel.run_selection(sub_rows, embs[idxs], aes[idxs], expo[idxs], TARGET)
    picks = result["picks"]
    quality = result["quality"]
    names3 = []
    for j, r in enumerate(sub_rows):
        pick = picks.get(r["id"], 0)
        db.execute(
            "UPDATE photos SET rating=?, ai_pick=?, aesthetic=?, exposure_penalty=?, "
            "quality=?, embedding=? WHERE id=?",
            (pick, pick,
             float(aes[idxs[j]]) if not np.isnan(aes[idxs[j]]) else None,
             float(expo[idxs[j]]), float(quality[j]),
             embs[idxs[j]].astype(np.float16).tobytes(), r["id"]))
        xmp.write_sidecar(r["path"], pick, r["color_label"])
        if pick == 3:
            names3.append(r["filename"])
    db.commit()
    (Path(__file__).parent / f"stage_{s + 1}.txt").write_text(
        "\n".join(names3), encoding="utf-8")
    st = result["stats"]
    print(f"무대{s + 1}: {f(t0)}~{f(t1)} 총 {len(idxs)}장 → ★3 {st['star3']} / "
          f"★2 {st['star2']} / ★1 {st['star1']} / 불량 {st['flagged']}")
