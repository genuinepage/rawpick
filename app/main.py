"""rawpick — RAW 셀렉 툴 로컬 서버.

실행: uv run --no-sync uvicorn app.main:app --port 8765
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analyze, previews, xmp
from .catalog import get_db, row_to_dict

RAW_EXTS = {".arw"}  # 소니. 필요시 .cr3 .nef 등 추가
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="rawpick")

# 폴더별 진행상황: {folder: {"total": n, "done": n, "state": "scanning|building|done"}}
_progress: dict[str, dict] = {}
_progress_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=6)


# ---------- 스캔 & 백그라운드 프리뷰/분석 ----------

class ScanReq(BaseModel):
    folder: str
    recursive: bool = True


def _process_photo(photo_id: int, raw_path: str, key: str, folder: str):
    try:
        db = get_db()
        ok, meta = previews.build_previews(raw_path, key)
        result = None
        if ok:
            try:
                result = analyze.analyze_image(str(previews.preview_path(key)))
            except Exception:
                result = None
        if result:
            db.execute(
                "UPDATE photos SET preview_ok=?, analyzed=1, sharpness=?, face_count=?, "
                "face_sharpness=?, meta=? WHERE id=?",
                (1 if ok else 0, result["sharpness"], result["face_count"],
                 result["face_sharpness"], json.dumps(meta, ensure_ascii=False), photo_id))
        else:
            db.execute("UPDATE photos SET preview_ok=?, analyzed=1, meta=? WHERE id=?",
                       (1 if ok else 0, json.dumps(meta, ensure_ascii=False), photo_id))
        db.commit()
    except Exception:
        import logging
        logging.exception("process_photo 실패: %s", raw_path)
    with _progress_lock:
        p = _progress.get(folder)
        if p:
            p["done"] += 1
            if p["done"] >= p["total"]:
                p["state"] = "flagging"
    p = _progress.get(folder)
    if p and p["state"] == "flagging":
        _apply_cull_flags(folder)
        with _progress_lock:
            p["state"] = "done"


def _apply_cull_flags(folder: str):
    db = get_db()
    rows = [dict(r) for r in db.execute(
        "SELECT id, sharpness, face_sharpness FROM photos WHERE folder=? AND analyzed=1",
        (folder,))]
    flags = analyze.compute_cull_flags(rows)
    db.executemany("UPDATE photos SET cull_flag=? WHERE id=?",
                   [(f, pid) for pid, f in flags.items()])
    db.commit()


@app.post("/api/scan")
def scan(req: ScanReq):
    folder = str(Path(req.folder).resolve())
    root = Path(folder)
    if not root.is_dir():
        raise HTTPException(400, f"폴더가 없습니다: {folder}")
    # 이미 처리 중인 폴더는 재큐잉하지 않는다 (이중 처리 방지)
    cur = _progress.get(folder)
    if cur and cur["state"] in ("building", "flagging"):
        return {"folder": folder, "files": cur.get("file_count", 0),
                "to_process": cur["total"], "already_running": True}
    pattern = "**/*" if req.recursive else "*"
    files = sorted(p for p in root.glob(pattern)
                   if p.suffix.lower() in RAW_EXTS and p.is_file())
    db = get_db()
    new_jobs = []
    for f in files:
        st = f.stat()
        path = str(f)
        row = db.execute("SELECT id, mtime, preview_ok, analyzed FROM photos WHERE path=?",
                         (path,)).fetchone()
        side = xmp.read_sidecar(path)  # 기존 사이드카 별점은 항상 정본으로 반영
        if row is None:
            cur = db.execute(
                "INSERT INTO photos(path, folder, filename, mtime, size, rating, color_label) "
                "VALUES(?,?,?,?,?,?,?)",
                (path, folder, f.name, st.st_mtime, st.st_size,
                 side.get("rating", 0), side.get("color_label", "")))
            new_jobs.append((cur.lastrowid, path, previews.cache_key(path, st.st_mtime)))
        else:
            if side:
                db.execute("UPDATE photos SET rating=?, color_label=? WHERE id=?",
                           (side.get("rating", 0), side.get("color_label", ""), row["id"]))
            if row["mtime"] != st.st_mtime or not row["preview_ok"] or not row["analyzed"]:
                db.execute("UPDATE photos SET mtime=?, analyzed=0 WHERE id=?",
                           (st.st_mtime, row["id"]))
                new_jobs.append((row["id"], path, previews.cache_key(path, st.st_mtime)))
    db.commit()

    with _progress_lock:
        _progress[folder] = {"total": len(new_jobs), "done": 0,
                             "state": "building" if new_jobs else "done",
                             "file_count": len(files)}
    for pid, path, key in new_jobs:
        _executor.submit(_process_photo, pid, path, key, folder)
    if not new_jobs:
        _apply_cull_flags(folder)
    return {"folder": folder, "files": len(files), "to_process": len(new_jobs)}


@app.get("/api/progress")
def progress(folder: str):
    folder = str(Path(folder).resolve())
    return _progress.get(folder, {"total": 0, "done": 0, "state": "idle"})


@app.get("/api/photos")
def photos(folder: str):
    folder = str(Path(folder).resolve())
    db = get_db()
    rows = db.execute(
        "SELECT * FROM photos WHERE folder=? ORDER BY filename", (folder,)).fetchall()
    return [row_to_dict(r) for r in rows]


# ---------- 별점 / 라벨 / 리젝트 ----------

class RateReq(BaseModel):
    ids: list[int]
    rating: int


@app.post("/api/rating")
def set_rating(req: RateReq):
    rating = max(0, min(5, req.rating))
    db = get_db()
    for pid in req.ids:
        row = db.execute("SELECT path, color_label FROM photos WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        db.execute("UPDATE photos SET rating=? WHERE id=?", (rating, pid))
        xmp.write_sidecar(row["path"], rating, row["color_label"])
    db.commit()
    return {"ok": True}


class LabelReq(BaseModel):
    ids: list[int]
    label: str  # '', red, yellow, green, blue, purple


@app.post("/api/label")
def set_label(req: LabelReq):
    db = get_db()
    for pid in req.ids:
        row = db.execute("SELECT path, rating FROM photos WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        db.execute("UPDATE photos SET color_label=? WHERE id=?", (req.label, pid))
        xmp.write_sidecar(row["path"], row["rating"], req.label)
    db.commit()
    return {"ok": True}


class RejectReq(BaseModel):
    ids: list[int]
    rejected: bool


@app.post("/api/reject")
def set_reject(req: RejectReq):
    db = get_db()
    db.executemany("UPDATE photos SET rejected=? WHERE id=?",
                   [(1 if req.rejected else 0, pid) for pid in req.ids])
    db.commit()
    return {"ok": True}


# ---------- AI 목표컷 셀렉 ----------

_select_progress: dict[str, dict] = {}


class AutoSelectReq(BaseModel):
    folder: str
    target: int = 1500


def _run_autoselect(folder: str, target: int):
    from . import select as sel
    import numpy as np
    db = get_db()
    try:
        rows = [row_to_dict(r) for r in db.execute(
            "SELECT * FROM photos WHERE folder=? AND preview_ok=1 ORDER BY filename",
            (folder,)).fetchall()]
        if not rows:
            _select_progress[folder] = {"state": "error", "msg": "분석된 사진이 없습니다"}
            return

        paths = []
        for r in rows:
            paths.append(str(previews.preview_path(
                previews.cache_key(r["path"], r["mtime"]))))

        def cb(done, total):
            _select_progress[folder] = {"state": "scoring", "done": done, "total": total}

        _select_progress[folder] = {"state": "loading_model", "done": 0, "total": len(rows)}
        embs, aes = sel.embed_and_score(paths, progress_cb=cb)

        _select_progress[folder] = {"state": "exposure", "done": 0, "total": len(rows)}
        expo = np.array([sel.exposure_penalty(
            str(previews.thumb_path(previews.cache_key(r["path"], r["mtime"]))))
            for r in rows], dtype=np.float32)

        _select_progress[folder] = {"state": "ranking", "done": 0, "total": len(rows)}
        result = sel.run_selection(rows, embs, aes, expo, target)

        picks = result["picks"]
        quality = result["quality"]
        for i, r in enumerate(rows):
            pick = picks.get(r["id"], 0)  # 플래그컷 = 0
            db.execute(
                "UPDATE photos SET rating=?, ai_pick=?, aesthetic=?, exposure_penalty=?, "
                "quality=?, embedding=? WHERE id=?",
                (pick, pick,
                 float(aes[i]) if not np.isnan(aes[i]) else None,
                 float(expo[i]), float(quality[i]),
                 embs[i].astype(np.float16).tobytes(), r["id"]))
            xmp.write_sidecar(r["path"], pick, r["color_label"])
            if i % 200 == 0:
                db.commit()
                _select_progress[folder] = {"state": "writing", "done": i, "total": len(rows)}
        db.commit()
        _select_progress[folder] = {"state": "done", **result["stats"]}
    except Exception as e:
        import logging
        logging.exception("autoselect 실패")
        _select_progress[folder] = {"state": "error", "msg": str(e)}


@app.post("/api/autoselect")
def autoselect(req: AutoSelectReq):
    folder = str(Path(req.folder).resolve())
    cur = _select_progress.get(folder)
    if cur and cur.get("state") not in (None, "done", "error"):
        return {"already_running": True}
    _select_progress[folder] = {"state": "loading_model", "done": 0, "total": 0}
    threading.Thread(target=_run_autoselect, args=(folder, req.target), daemon=True).start()
    return {"started": True, "target": req.target}


@app.get("/api/autoselect/progress")
def autoselect_progress(folder: str):
    folder = str(Path(folder).resolve())
    return _select_progress.get(folder, {"state": "idle"})


# ---------- JPEG 내보내기 ----------

_export_progress: dict[str, dict] = {}


class ExportReq(BaseModel):
    folder: str
    rating: int          # 이 별점인 컷만
    max_mb: float = 6.0
    mode: str = "raw"    # raw=풀디코드(고화질) | embedded=카메라 내장 JPEG(초고속)
    only_files: list[str] = []  # 지정 시 해당 파일명만 (증분 재출력용)
    straighten: bool = False    # DB의 tilt 기반 수평 보정 (0.3~3°만, 더치앵글 제외)
    lift: bool = False   # 어두운 컷 하한선 리프트 + 톤커브 (암부↓ 명부↑ 미드톤↑)
    lift_min_ev: float = 1.0   # 어두운 컷으로 분류되면 최소 이만큼 리프트
    lift_max_ev: float = 3.0
    out_dir: str = ""    # 비우면 <folder>/_export/star<rating>


def _run_export(folder: str, rating: int, max_mb: float, out_dir: str,
                mode: str = "raw", lift: bool = False,
                lift_min_ev: float = 1.0, lift_max_ev: float = 3.0,
                only_files: list[str] | None = None, straighten: bool = False):
    import math
    from . import export as exp
    db = get_db()
    key = f"{folder}|{rating}"
    try:
        rows = db.execute(
            "SELECT path, filename, brightness, brightness_mid, meta, tilt FROM photos "
            "WHERE folder=? AND rating=? ORDER BY filename",
            (folder, rating)).fetchall()
        if only_files:
            keep = set(only_files)
            rows = [r for r in rows if r["filename"] in keep]
        # 장면 스무딩용: ★2+★3 전체 (노출설정·시각 기반)
        all_rows = [row_to_dict(r) for r in db.execute(
            "SELECT id, filename, mtime, brightness, brightness_mid, meta FROM photos "
            "WHERE folder=? AND rating >= 2 ORDER BY filename", (folder,)).fetchall()]

        # 2단 보정 (연출 어두움 보존 — 배경·암부는 유지, 피사체 구간만):
        #  1) 노출 리프트: 피사체 하이라이트 p99(피부·림라이트·흰 의상)를
        #     셀렉 중앙값(상한 0.85)까지 부족분만큼. 전체가 어두운 컷용.
        #  2) 미드톤 감마: 리프트 후에도 피부 구간(p50)이 어두우면 부족분의 절반만
        #     "살짝" 상승. 강한 국소광(발광체) 컷에서 하이라이트 안 밀고 피부만 올림.
        # 목표값: 하이라이트는 고정 0.75 (셀렉 중앙값 0.37 수준 공연이라 상대 기준은 부족),
        # 미드톤은 셀렉 분포 기반(상한 0.30). 부족분의 80%만 적용해 톤 순서는 보존.
        hi_target = mid_target = None
        if lift:
            hi_target = 0.75
            mv = sorted(r[0] for r in db.execute(
                "SELECT brightness_mid FROM photos WHERE folder=? AND rating >= 2 "
                "AND brightness_mid IS NOT NULL", (folder,)))
            if mv:
                mid_target = min(mv[len(mv) // 2], 0.30)

        def adjust_of(p99, p50):
            """(lift_ev, mid_gamma) 계산."""
            lift_ev = 0.0
            if hi_target and p99 and p99 > 0:
                deficit = max(0.0, math.log2(hi_target / p99))
                # 기본 80% + 전역 부스트 +0.75EV (사용자 요청: 평균 0.5~1EV 상향).
                # 부족분이 작은 컷은 부스트를 비례 축소해 밝은 컷과의 경계 튐 방지.
                boost = 0.75 * min(1.0, deficit / 0.5)
                lift_ev = min(3.5, 0.8 * deficit + boost)
            mid_gamma = 1.0
            if mid_target and p50 and p50 > 0:
                lifted_mid = p50 * (2.0 ** lift_ev)
                remain = max(0.0, math.log2(mid_target / lifted_mid))
                # 부족분 절반만, 감마 하한 0.72 (과보정 방지)
                mid_gamma = max(0.72, 1.0 - 0.25 * min(remain, 1.12 * 2))
            return lift_ev, mid_gamma

        # ---- 질감 복원 목표: 같은 폴더 저감도(ISO<=1000) 밝은 컷의 미세대역 에너지 ----
        texture_target = None
        if lift:
            try:
                ref = db.execute(
                    "SELECT path FROM photos WHERE folder=? AND rating>=2 "
                    "AND brightness > 0.5 AND json_extract(meta,'$.iso') <= 1000 "
                    "LIMIT 1", (folder,)).fetchone()
                if ref:
                    import rawpy
                    from . import texture
                    with rawpy.imread(ref["path"]) as raw:
                        ref_rgb = raw.postprocess(use_camera_wb=True,
                                                  no_auto_bright=True, output_bps=8)
                    texture_target = texture.fine_std(ref_rgb)
            except Exception:
                import logging
                logging.exception("질감 레퍼런스 계산 실패 — 그레인 매칭 생략")

        # ---- 장면 스무딩: 같은 노출설정(ISO·셔터·조리개) + 30초 이내 연속 컷은
        #      보정값을 장면 중앙값으로 통일 → 인접 컷 간 노출 출렁임 방지 ----
        from .select import _parse_dt
        adjust_by_name: dict[str, tuple] = {}
        if lift and all_rows:
            seq = sorted(all_rows, key=lambda r: (_parse_dt(r["meta"], r["mtime"]),
                                                  r["filename"]))
            scenes, cur, prev_key, prev_t = [], [], None, None
            for r in seq:
                m = r["meta"]
                exp_key = (m.get("iso"), m.get("shutter"), m.get("aperture"))
                t = _parse_dt(m, r["mtime"])
                if cur and (exp_key != prev_key or t - prev_t > 30):
                    scenes.append(cur)
                    cur = []
                cur.append(r)
                prev_key, prev_t = exp_key, t
            if cur:
                scenes.append(cur)
            for sc in scenes:
                adjusts = [adjust_of(r["brightness"], r["brightness_mid"]) for r in sc]
                lifts = sorted(a[0] for a in adjusts)
                gammas = sorted(a[1] for a in adjusts)
                med_lift = lifts[len(lifts) // 2]
                med_gamma = gammas[len(gammas) // 2]
                for r, own in zip(sc, adjusts):
                    # 장면 중앙값을 따르되 본인 계산값 ±0.3EV / ±0.07 밴드로 클램프.
                    # 스모그·조명으로 이미 밝은 컷(본인값 0)이 이웃 어두운 컷 때문에
                    # 끌려 올라가는 것을 방지 (원노출이 좋았던 컷은 유지).
                    lift_c = max(own[0] - 0.3, min(own[0] + 0.3, med_lift))
                    gamma_c = max(own[1] - 0.07, min(own[1] + 0.07, med_gamma))
                    adjust_by_name[r["filename"]] = (lift_c, gamma_c)
        out = Path(out_dir) if out_dir else Path(folder) / "_export" / f"star{rating}"
        _export_progress[key] = {"state": "exporting", "done": 0, "total": len(rows)}
        done = fail = recomp = 0
        total_bytes = 0
        def nr_level_of(meta_json: str, lift_ev: float) -> int:
            """실효 ISO(촬영 ISO × 2^리프트EV) 기반 노이즈리덕션 단계.

            +1EV 리프트는 ISO 2배와 같은 노이즈를 만들므로 리프트분까지 반영.
            """
            try:
                iso = json.loads(meta_json or "{}").get("iso")
            except (ValueError, TypeError):
                iso = None
            if not iso:
                return 0
            eff = iso * (2.0 ** lift_ev)
            # v3: 사용자 요청으로 전 구간 1단계 승격 + 최하단(3200) 신설
            if eff >= 12800:
                return 5
            if eff >= 10000:
                return 4
            if eff >= 8000:
                return 3
            if eff >= 5000:
                return 2
            if eff >= 3200:
                return 1
            return 0

        futures = []
        for r in rows:
            lift_ev, mid_gamma = adjust_by_name.get(
                r["filename"], adjust_of(r["brightness"], r["brightness_mid"]))
            nr = nr_level_of(r["meta"], lift_ev)
            rot = 0.0
            if straighten:
                from .tilt import correction_angle
                rot = correction_angle(r["tilt"])
            futures.append(_executor.submit(
                exp.export_jpeg, r["path"], out / (Path(r["filename"]).stem + ".jpg"),
                max_mb, mode, lift_ev, mid_gamma, nr, rot, texture_target))
        for f in futures:
            try:
                res = f.result()
                done += 1
                total_bytes += res["size"]
                recomp += 1 if res["recompressed"] else 0
            except Exception:
                fail += 1
            _export_progress[key]["done"] = done + fail
        _export_progress[key] = {
            "state": "done", "done": done, "fail": fail, "total": len(rows),
            "recompressed": recomp, "avg_mb": round(total_bytes / max(1, done) / 1048576, 2),
            "out": str(out)}
    except Exception as e:
        import logging
        logging.exception("export 실패")
        _export_progress[key] = {"state": "error", "msg": str(e)}


@app.post("/api/export")
def export_photos(req: ExportReq):
    folder = str(Path(req.folder).resolve())
    key = f"{folder}|{req.rating}"
    cur = _export_progress.get(key)
    if cur and cur.get("state") == "exporting":
        return {"already_running": True}
    _export_progress[key] = {"state": "exporting", "done": 0, "total": 0}
    threading.Thread(target=_run_export,
                     args=(folder, req.rating, req.max_mb, req.out_dir, req.mode,
                           req.lift, req.lift_min_ev, req.lift_max_ev,
                           req.only_files or None, req.straighten),
                     daemon=True).start()
    return {"started": True}


@app.get("/api/export/progress")
def export_progress(folder: str, rating: int):
    folder = str(Path(folder).resolve())
    return _export_progress.get(f"{folder}|{rating}", {"state": "idle"})


# ---------- 이미지 서빙 ----------

def _photo_or_404(pid: int):
    row = get_db().execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


@app.get("/api/thumb/{pid}")
def thumb(pid: int):
    row = _photo_or_404(pid)
    p = previews.thumb_path(previews.cache_key(row["path"], row["mtime"]))
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


@app.get("/api/preview/{pid}")
def preview(pid: int):
    row = _photo_or_404(pid)
    p = previews.preview_path(previews.cache_key(row["path"], row["mtime"]))
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


@app.get("/")
def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
