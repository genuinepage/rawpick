"""공연 구간별 추가 셀렉 — 기존 셀렉분을 제외하고 품질 상위 N장을 추가 선발.

사용: python scripts/extra_select.py <RAW 폴더> <구간폴더명> <추가장수>
  1) 해당 구간 폴더의 기존 셀렉 파일들로 시간 범위를 파악
  2) 그 시간 범위 안의 모든 컷 중 아직 안 뽑힌 것을 후보로
  3) 불량 플래그 제외 + 기존 셀렉과 너무 유사한 연사 중복 제외
  4) quality 상위 N장 선발 → rating=3, ai_pick=3 으로 DB·XMP 반영
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db, row_to_dict  # noqa: E402
from app.select import _parse_dt, SIM_THRESHOLD  # noqa: E402
from app import xmp  # noqa: E402

if len(sys.argv) < 3:
    raise SystemExit("사용법: python scripts/extra_select.py <RAW 폴더> <구간폴더명> [추가장수=100]")
FOLDER = str(Path(sys.argv[1]).resolve())
SELECTS = Path(FOLDER) / "_export" / "selects"
section = sys.argv[2]
want = int(sys.argv[3]) if len(sys.argv) > 3 else 100

db = get_db()
existing_names = {p.stem for p in (SELECTS / section).glob("*.jpg")}
all_selected = {p.stem for p in SELECTS.rglob("*.jpg")}
print(f"구간 {section}: 기존 {len(existing_names)}장 / 전체 셀렉 {len(all_selected)}장")

rows = [row_to_dict(r) for r in db.execute(
    "SELECT id, path, filename, mtime, meta, quality, cull_flag, embedding, rating "
    "FROM photos WHERE folder=?", (FOLDER,)).fetchall()]
by_stem = {Path(r["filename"]).stem: r for r in rows}

# 1) 구간 시간 범위
times = [_parse_dt(by_stem[n]["meta"], by_stem[n]["mtime"])
         for n in existing_names if n in by_stem]
if not times:
    raise SystemExit(f"구간 {section}의 기존 셀렉을 DB에서 찾지 못했습니다")
t_start, t_end = min(times), max(times)
print(f"시간 범위: {t_end - t_start:.0f}초 구간")

# 2) 후보: 시간 범위 내 + 미선발 + 불량 아님
def emb_of(r):
    b = r.get("embedding")
    return np.frombuffer(b, dtype=np.float16).astype(np.float32) if b else None


sel_embs = []
for n in existing_names:
    r = by_stem.get(n)
    if r is not None:
        e = emb_of(r)
        if e is not None:
            sel_embs.append(e)
sel_mat = np.array(sel_embs) if sel_embs else None

cands = []
for r in rows:
    stem = Path(r["filename"]).stem
    if stem in all_selected or r["cull_flag"] or r["quality"] is None:
        continue
    t = _parse_dt(r["meta"], r["mtime"])
    if not (t_start <= t <= t_end):
        continue
    cands.append(r)
print(f"후보(구간 내 미선발·불량제외): {len(cands)}장")

# 3) 기존 셀렉과 유사한 연사 중복 제외
picked = []
picked_embs = []
for r in sorted(cands, key=lambda x: -x["quality"]):
    e = emb_of(r)
    if e is not None:
        if sel_mat is not None and float(np.max(sel_mat @ e)) >= SIM_THRESHOLD:
            continue  # 기존 셀렉과 거의 같은 컷
        if picked_embs and max(float(pe @ e) for pe in picked_embs) >= SIM_THRESHOLD:
            continue  # 이번에 뽑은 것끼리 중복
        picked_embs.append(e)
    picked.append(r)
    if len(picked) >= want:
        break

print(f"선발: {len(picked)}장")
for r in picked:
    db.execute("UPDATE photos SET rating=3, ai_pick=3 WHERE id=?", (r["id"],))
    xmp.write_sidecar(r["path"], 3, "")
db.commit()

out = Path(__file__).resolve().parent / "extra_picks.txt"
out.write_text("\n".join(r["filename"] for r in picked), encoding="utf-8")
print(f"명단 저장: {out}")
