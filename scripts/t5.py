import tifffile
f = r"D:\20260824 창무 국제 공연 예술제\photo\DSC02117.ARW"
with tifffile.TiffFile(f) as t:
    p0 = t.pages[0]
    print("Model:", p0.tags.get(272).value if p0.tags.get(272) else None)
    print("Orient:", p0.tags.get(274).value if p0.tags.get(274) else None)
    print("DateTime:", p0.tags.get(306).value if p0.tags.get(306) else None)
    et = p0.tags.get(34665)
    print("ExifTag type:", type(et.value).__name__)
    if isinstance(et.value, dict):
        v = et.value
        print("ISO", v.get("ISOSpeedRatings"), "Exp", v.get("ExposureTime"), "F", v.get("FNumber"), "focal", v.get("FocalLength"), "dt", v.get("DateTimeOriginal"))
    arr = t.pages[2].asarray()
    print("풀사이즈:", arr.shape)
