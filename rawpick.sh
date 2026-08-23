#!/bin/sh
# rawpick 단독 실행 (맥/리눅스) — 저장소 루트에서 실행
cd "$(dirname "$0")"
(sleep 2 && open http://localhost:8765) &
uv run --no-sync uvicorn app.main:app --port 8765
