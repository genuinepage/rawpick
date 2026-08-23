# rawpick

소니 ARW RAW 셀렉(컬링)·보정·출력 툴 — 포토 메카닉/이보토 스타일의 빠른 브라우징 + 별점 + AI 셀렉 + 자동 보정 내보내기.

## 실행

```powershell
uv run --no-sync --directory C:\projects\rawpick uvicorn app.main:app --port 8765
```

브라우저에서 http://localhost:8765 (단독 실행: `rawpick.bat`). 폴더 경로 입력 → 스캔.

## 파이프라인 (2026-08 공연촬영 5,066장으로 실전 검증)

1. **카탈로그**: RAW 디코딩 없이 임베디드 JPEG 추출·캐시(`~/.rawpick/`, 약 15장/초),
   EXIF 요약, SQLite 인덱스
2. **자동 컬링**: 라플라시안 선명도(전역+얼굴영역, 폴더 분포 상대판정) → 흐림/핀아웃 플래그
3. **AI 셀렉** (`/api/autoselect`): CLIP ViT-B/32 임베딩 + LAION 미학점수(GPU) →
   연사 그룹핑(4초+코사인 0.90) → 10분 시간대 쿼터 → 목표수량 선발.
   별점: ★3 선발 / ★2 차점 / ★1 통과 / 0 불량. 확정 후 ★4 승격(`scripts/finalize_ratings.py`)
4. **취향 학습** (`scripts/train_taste.py`): 사람의 확정/탈락 판단을 임베딩으로 학습 →
   다음 셀렉의 quality 점수에 보조 가중(W_TASTE)으로 반영. 회차가 쌓일수록 정확해짐
5. **내보내기** (`/api/export`): rawpy 풀디코드 후
   - 노출 리프트: 피사체 하이라이트 p99 기준 부족분 80% + 0.75EV 부스트, 캡 3.5EV,
     하이라이트 보존. 장면 스무딩(동일 ISO·셔터·조리개 + 30초 연속 → 중앙값, 본인값 ±0.3EV 클램프)
   - 미드톤 감마(피부 구간만) + 블랙포인트 재고정(리프트 비례, 뿌연 암부 방지)
   - **AI 디노이즈**: 실효 ISO(촬영 ISO × 2^리프트EV) 3200 이상 → SCUNet fp16 타일 추론
     (RTX 3090 기준 24MP 장당 ~10초). 미만은 FBDD 고전 NR
   - 수평보정: Hough 바닥선 검출(CLAHE 전처리), 0.3~5°만, 더치앵글·저신뢰 제외
   - JPEG 품질 95 상한 + 목표용량(6~10MB) 이진탐색, EXIF 이식
6. **XMP 사이드카**: 별점·컬러라벨을 라이트룸/캡처원 호환으로 항시 동기화

## 별점 체계

★4 확정(사람) · ★3 AI 선발 · ★2 차점 · ★1 통과/탈락하향 · 0 불량플래그

## 의존성 메모

- `opencv-python<5` 고정 (5.0에서 CascadeClassifier 제거)
- SCUNet: `third_party/SCUNet`에 클론(`git clone --depth 1 https://github.com/cszn/SCUNet`),
  가중치는 KAIR 릴리스에서 `~/.rawpick/models/scunet_color_real_psnr.pth`
  (SCUNet 저장소 릴리스가 아니라 **KAIR** 릴리스임에 주의)
- torch는 cu124 인덱스로 설치 (pyproject 참조)

## 실측 교훈 (재발 방지)

- p90/p50 밝기 지표는 무대 안개·백라이트에 속는다 → 피사체 하이라이트는 **p99**
- 장면 전파 수평보정은 핸드헬드에서 위험(같은 장면에서도 컷마다 기울기 다름) → 측정 일관 시에만
- AI NR 경계 아래 고전 NR 컷이 더 지저분해 보이는 **역전현상** → 경계를 3200까지 하향
- a9M3 글로벌셔터 + 무대 LED 플리커 = 연사 중 컷 단위 노출 튐 (촬영 시 Anti-flicker Hi 권장)
- fp16 autocast + 타일 배치로 SCUNet 2.1배 (품질 동일)
