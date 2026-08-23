"""XMP 사이드카 읽기/쓰기 — 라이트룸·캡처원 호환 별점(xmp:Rating)·컬러라벨(xmp:Label).

사이드카 파일명은 어도비 규약을 따른다: DSC0001.ARW → DSC0001.xmp
기존 사이드카가 있으면 다른 메타데이터를 보존한 채 Rating/Label만 갱신한다.
"""
import re
from pathlib import Path

NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_XMP = "http://ns.adobe.com/xap/1.0/"

TEMPLATE = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="rawpick">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="{rating}"{label_attr}/>
 </rdf:RDF>
</x:xmpmeta>
"""

# 어도비 컬러라벨 표준 명칭
LABELS = {"red": "Red", "yellow": "Yellow", "green": "Green", "blue": "Blue", "purple": "Purple"}


def sidecar_path(raw_path: str) -> Path:
    return Path(raw_path).with_suffix(".xmp")


def read_sidecar(raw_path: str) -> dict:
    """기존 사이드카에서 rating/label 읽기. 없으면 빈 dict."""
    sp = sidecar_path(raw_path)
    if not sp.exists():
        return {}
    try:
        text = sp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    m = re.search(r'xmp:Rating\s*=\s*"(-?\d+)"', text) or re.search(
        r"<xmp:Rating>\s*(-?\d+)\s*</xmp:Rating>", text)
    if m:
        out["rating"] = max(0, min(5, int(m.group(1))))
    m = re.search(r'xmp:Label\s*=\s*"([^"]*)"', text) or re.search(
        r"<xmp:Label>\s*([^<]*?)\s*</xmp:Label>", text)
    if m:
        out["color_label"] = m.group(1).strip().lower()
    return out


def write_sidecar(raw_path: str, rating: int, color_label: str = "") -> None:
    """Rating/Label 갱신. 기존 사이드카가 있으면 해당 값만 치환해 나머지 보존."""
    sp = sidecar_path(raw_path)
    label = LABELS.get(color_label.lower(), "") if color_label else ""

    if sp.exists():
        text = sp.read_text(encoding="utf-8", errors="replace")
        text, n = re.subn(r'(xmp:Rating\s*=\s*")-?\d+(")', rf"\g<1>{rating}\g<2>", text)
        if n == 0:
            text, n = re.subn(r"(<xmp:Rating>)\s*-?\d+\s*(</xmp:Rating>)",
                              rf"\g<1>{rating}\g<2>", text)
        if n == 0:
            # Rating 속성이 없는 사이드카: 첫 rdf:Description에 주입
            text, n = re.subn(r"(<rdf:Description\b)", rf'\g<1> xmp:Rating="{rating}"',
                              text, count=1)
        if "xmlns:xmp" not in text:
            text = re.sub(r"(<rdf:Description\b)",
                          r'\g<1> xmlns:xmp="http://ns.adobe.com/xap/1.0/"', text, count=1)
        # Label 갱신 (있으면 치환, 없고 값이 있으면 주입)
        if re.search(r'xmp:Label\s*=', text) or re.search(r"<xmp:Label>", text):
            text = re.sub(r'(xmp:Label\s*=\s*")[^"]*(")', rf"\g<1>{label}\g<2>", text)
            text = re.sub(r"(<xmp:Label>)[^<]*(</xmp:Label>)", rf"\g<1>{label}\g<2>", text)
        elif label:
            text = re.sub(r"(<rdf:Description\b)", rf'\g<1> xmp:Label="{label}"', text, count=1)
        if n == 0 and "<rdf:Description" not in text:
            text = TEMPLATE.format(rating=rating,
                                   label_attr=f'\n    xmp:Label="{label}"' if label else "")
        sp.write_text(text, encoding="utf-8")
        return

    label_attr = f'\n    xmp:Label="{label}"' if label else ""
    sp.write_text(TEMPLATE.format(rating=rating, label_attr=label_attr), encoding="utf-8")
