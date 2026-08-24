import tifffile
from PIL import Image
f = r"D:\20260824 창무 국제 공연 예술제\photo\DSC02117.ARW"
img = Image.open(f)
ex = img.getexif()
ifd = ex.get_ifd(0x8769)
print("PIL EXIF:", ex.get(0x0110), "ISO", ifd.get(0x8827), "셔터", ifd.get(0x829A), "조리개", ifd.get(0x829D), "orient", ex.get(274))
with tifffile.TiffFile(f) as t:
    arr = t.pages[2].asarray()
print("풀사이즈 추출:", arr.shape)
