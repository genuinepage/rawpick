"""LibRaw 미지원 신기종(a7M5 등) ARW → DNG 일괄 변환.

Adobe DNG Converter CLI로 폴더의 ★4(기본) 컷을 <폴더>/_dng 에 변환한다.
export가 _dng 변환본을 자동으로 소스로 사용하므로, 변환 후 그대로 출력하면 된다.

사용: python scripts/convert_dng.py <RAW폴더> [별점=4]
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_db  # noqa: E402

CANDIDATES = [
    r"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe",
    "/Applications/Adobe DNG Converter.app/Contents/MacOS/Adobe DNG Converter",
]

FOLDER = str(Path(sys.argv[1]).resolve())
RATING = int(sys.argv[2]) if len(sys.argv) > 2 else 4
OUT = Path(FOLDER) / "_dng"
OUT.mkdir(exist_ok=True)

exe = next((p for p in CANDIDATES if Path(p).exists()), None)
if not exe:
    sys.exit("Adobe DNG Converter를 찾을 수 없음 — helpx.adobe.com에서 설치")

db = get_db()
paths = [r["path"] for r in db.execute(
    "SELECT path FROM photos WHERE folder=? AND rating=? ORDER BY filename",
    (FOLDER, RATING))]
todo = [p for p in paths if not (OUT / (Path(p).stem + ".dng")).exists()]
print(f"대상 {len(paths)}장 / 변환 필요 {len(todo)}장")

CHUNK = 200
for i in range(0, len(todo), CHUNK):
    subprocess.run([exe, "-c", "-d", str(OUT)] + todo[i:i + CHUNK],
                   capture_output=True)
    print(f"{min(i + CHUNK, len(todo))}/{len(todo)}", flush=True)
print(f"DNG 완료: {len(list(OUT.glob('*.dng')))}장")
