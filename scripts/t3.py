import tifffile, io
from PIL import Image
f = r"D:\20260824 창무 국제 공연 예술제\photo\DSC02117.ARW"
with tifffile.TiffFile(f) as t:
    for i, p in enumerate(t.pages):
        print(i, p.shape if hasattr(p, "shape") else "?", p.compression, p.photometric)
    # JpgFromRaw / PreviewImage 태그 탐색
    p0 = t.pages[0]
    for tag in p0.tags.values():
        if "JPEG" in str(tag.name) or tag.code in (513, 514, 46, 0x2001):
            print("tag:", tag.code, tag.name, tag.value if not isinstance(tag.value, bytes) else f"bytes({len(tag.value)})")
