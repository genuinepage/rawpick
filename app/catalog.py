"""SQLite 카탈로그 — 사진 목록·별점·분석 결과 저장.

DB는 프로젝트(=촬영 폴더) 단위가 아니라 전역 하나로 두고 folder 컬럼으로 구분한다.
별점의 정본은 XMP 사이드카이고 DB는 캐시 겸 인덱스다.
"""
import json
import sqlite3
import threading
from pathlib import Path

CACHE_ROOT = Path.home() / ".rawpick"
DB_PATH = CACHE_ROOT / "catalog.db"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,          -- RAW 파일 절대경로
    folder TEXT NOT NULL,               -- 소속 폴더 절대경로
    filename TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    rating INTEGER NOT NULL DEFAULT 0,  -- 0~5
    color_label TEXT NOT NULL DEFAULT '',
    rejected INTEGER NOT NULL DEFAULT 0,
    -- 분석 결과
    analyzed INTEGER NOT NULL DEFAULT 0,
    sharpness REAL,                     -- 전역 선명도 (라플라시안 분산, 로그스케일)
    face_count INTEGER,
    face_sharpness REAL,                -- 가장 큰 얼굴 영역 선명도
    cull_flag TEXT NOT NULL DEFAULT '', -- '', 'blurry', 'soft_face'
    meta TEXT NOT NULL DEFAULT '{}',    -- EXIF 요약 JSON
    preview_ok INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder);
"""


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        CACHE_ROOT.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        _local.conn = conn
    return conn


MIGRATE_COLS = [
    ("aesthetic", "REAL"),     # CLIP 미학점수 (원점수)
    ("exposure_penalty", "REAL"),  # 하이라이트/섀도 클리핑 비율
    ("quality", "REAL"),       # 종합 점수 (0~1)
    ("embedding", "BLOB"),     # CLIP 임베딩 float16 (연사 그룹핑용)
    ("ai_pick", "INTEGER NOT NULL DEFAULT 0"),  # 0=미실행 1=풀 2=차점 3=선발
    ("brightness", "REAL"),      # 피사체 하이라이트 p99 (리니어 0~1, 프리뷰 기준)
    ("brightness_mid", "REAL"),  # 미드톤 p50 (리니어) — 피부 밝기 구간
    ("tilt", "REAL"),            # 감지된 수평 기울기(도). NULL=기준선 없음/미측정
]


def _migrate(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    for name, decl in MIGRATE_COLS:
        if name not in cols:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {name} {decl}")
    conn.commit()


def row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["meta"] = json.loads(d.get("meta") or "{}")
    d.pop("embedding", None)  # 바이너리는 API로 내보내지 않음
    return d
