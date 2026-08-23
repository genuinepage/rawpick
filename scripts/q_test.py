import io, sys
from PIL import Image
from pathlib import Path
import numpy as np
src = Path(r"D:\20260820 공연촬영\photo\_export\selects\2")
f = sorted(src.glob("*.jpg"), key=lambda p: -p.stat().st_size)[0]  # 정보량 많은 컷
img = Image.open(f)
print("샘플:", f.name)
for q, sub in [(95, 1), (100, 1), (100, 0)]:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q, subsampling=sub, optimize=True)
    label = f"q{q}" + (" 4:4:4" if sub == 0 else " 4:2:2")
    print(f"{label}: {buf.tell()/1048576:.2f}MB")
# q95 vs q100 픽셀 차이 측정
b95, b100 = io.BytesIO(), io.BytesIO()
img.save(b95, "JPEG", quality=95, subsampling=1)
img.save(b100, "JPEG", quality=100, subsampling=1)
a = np.asarray(Image.open(io.BytesIO(b95.getvalue())), dtype=np.int16)
b = np.asarray(Image.open(io.BytesIO(b100.getvalue())), dtype=np.int16)
d = np.abs(a - b)
print(f"픽셀 차이: 평균 {d.mean():.3f}/255, 최대 {d.max()}, 2 초과 픽셀 비율 {(d>2).mean()*100:.2f}%")
