"""무대 경계 재판별 + 무대 2·3·4 재셀렉 (저장된 임베딩 재사용, GPU 불필요).

경계: 앵커 파일명 주변 ±12분 창에서 가장 큰 촬영 공백을 실제 경계로 채택.
사용: python scripts/restage.py <RAW 폴더>
"""
import datetime
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db, row_to_dict  # noqa: E402
from app import xmp  # noqa: E402
from app import select as sel  # noqa: E402

FOLDER = str(Path(sys.argv[1]).resolve())
ANCHORS = ["DSC02999.ARW", "DSC03253.ARW"]  # 무대3, 무대4 시작 앵커
PHOTOS_START = "DSC03557.ARW"               # 단체사진 시작 (확정)
TARGET = 250

db = get_db()
rows = [row_to_dict(r) for r in db.execute(
    "SELECT * FROM photos WHERE folder=? AND preview_ok=1 AND filename < ? "
    "ORDER BY filename", (FOLDER, PHOTOS_START)).fetchall()]
# row_to_dict는 embedding을 제거하므로 별도 조회
emb_map = {r[0]: r[1] for r in db.execute(
    "SELECT id, embedding FROM photos WHERE folder=?", (FOLDER,))}
times = np.array([sel._parse_dt(r["meta"], r["mtime"]) for r in rows])
order = np.argsort(times, kind="stable")
st = times[order]
fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")

# 무대1/2 경계: 전체에서 가장 큰 공백 (16:58→17:04 확인된 것)
gaps = np.diff(st)
b1 = int(np.argmax(gaps))
print(f"무대1|2 경계: {fmt(st[b1])} → {fmt(st[b1+1])} (공백 {gaps[b1]/60:.1f}분)")

bounds = [b1]
name_by_idx = {i: rows[order[i]]["filename"] for i in range(len(rows))}
for anchor in ANCHORS:
    try:
        ai = next(i for i in range(len(rows)) if name_by_idx[i] == anchor)
    except StopIteration:
        raise SystemExit(f"앵커 {anchor} 없음")
    t_anchor = st[ai]
    win = np.where(np.abs(st[:-1] - t_anchor) <= 12 * 60)[0]
    bi = int(win[np.argmax(gaps[win])])
    print(f"{anchor} 앵커 경계: {fmt(st[bi])} → {fmt(st[bi+1])} "
          f"(공백 {gaps[bi]/60:.1f}분, 경계 직후 파일 {name_by_idx[bi+1]})")
    bounds.append(bi)
bounds = sorted(set(bounds))

stage_of = np.zeros(len(rows), dtype=int)
prev = 0
for s, b in enumerate(bounds):
    stage_of[order[prev:b + 1]] = s
    prev = b + 1
stage_of[order[prev:]] = len(bounds)

# 무대 2·3·4 재셀렉 (무대1은 기존 유지)
for s in range(1, len(bounds) + 1):
    idxs = np.where(stage_of == s)[0]
    sub = [rows[i] for i in idxs]
    embs = np.stack([np.frombuffer(emb_map[r["id"]], dtype=np.float16).astype(np.float32)
                     if emb_map.get(r["id"]) else np.zeros(512, np.float32) for r in sub])
    aes = np.array([r["aesthetic"] if r["aesthetic"] is not None else np.nan
                    for r in sub], dtype=np.float32)
    expo = np.array([r["exposure_penalty"] or 0.0 for r in sub], dtype=np.float32)
    result = sel.run_selection(sub, embs, aes, expo, TARGET)
    picks = result["picks"]
    names3 = []
    for r in sub:
        pick = picks.get(r["id"], 0)
        db.execute("UPDATE photos SET rating=?, ai_pick=? WHERE id=?",
                   (pick, pick, r["id"]))
        xmp.write_sidecar(r["path"], pick, r["color_label"])
        if pick == 3:
            names3.append(r["filename"])
    db.commit()
    (Path(__file__).parent / f"stage_{s + 1}.txt").write_text(
        "\n".join(names3), encoding="utf-8")
    t0, t1 = times[idxs].min(), times[idxs].max()
    stt = result["stats"]
    print(f"무대{s + 1}: {fmt(t0)}~{fmt(t1)} {len(idxs)}장 "
          f"({sub[0]['filename']}~{sub[-1]['filename']}) → ★3 {stt['star3']} / "
          f"★2 {stt['star2']} / 불량 {stt['flagged']}")
