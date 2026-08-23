@echo off
rem rawpick 단독 실행 — 서버 띄우고 브라우저 열기
start "" http://localhost:8765
uv run --no-sync --directory C:\projects\rawpick uvicorn app.main:app --port 8765
