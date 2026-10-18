"""보고서 PDF 배치 점검: 최소 글자 크기, 글줄 겹침, 상자·그림 경계 걸침, 쪽 밖 글자, 줄표(—) 수.

사용: python scripts/report/qa_layout.py [pdf] [--min 7.4]
그림(PNG) 안의 글자는 PDF 글자가 아니므로 대상이 아니다(그림 생성기에서 7.5pt 이상으로 관리).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
MM = 72 / 25.4


def inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return (w, h) if w > 0 and h > 0 else (0, 0)


def inside(a, b, tol=0.6):
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def lines_of(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0 = min(s["bbox"][0] for s in spans); x1 = max(s["bbox"][2] for s in spans)
            # 글줄 높이는 글자 크기 기준(행간 여백 제외)으로 잡아 정상 행간을 겹침으로 보지 않게 한다
            y0 = min(s["origin"][1] - s["size"] * 0.82 for s in spans); y1 = max(s["origin"][1] + s["size"] * 0.2 for s in spans)
            out.append({"bbox": (x0, y0, x1, y1), "text": "".join(s["text"] for s in spans),
                        "size": min(s["size"] for s in spans)})
    return out


def boxes_of(page):
    rects = []
    for d in page.get_drawings():
        r = d["rect"]
        if d.get("fill") is None or r.width < 8 * MM or r.height < 4 * MM:
            continue
        if r.width > 200 * MM and r.height > 280 * MM:      # 쪽 배경
            continue
        rects.append((r.x0, r.y0, r.x1, r.y1))
    return rects


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--min", type=float, default=7.4)
    a = ap.parse_args()
    pdf = Path(a.pdf) if a.pdf else max((ROOT / "outputs" / "report").glob("*_분석보고서.pdf"), key=lambda p: p.stat().st_mtime)
    doc = fitz.open(pdf)
    total = 0
    for pno, page in enumerate(doc, 1):
        issues = []
        L = lines_of(page)
        W, H = page.rect.width, page.rect.height
        small = sorted({(round(l["size"], 1), l["text"][:30]) for l in L if l["size"] < a.min - 0.05})
        for s, t in small[:12]:
            issues.append(f"작은 글자 {s}pt: {t}")
        if len(small) > 12:
            issues.append(f"작은 글자 외 {len(small) - 12}건")
        for l in L:
            x0, y0, x1, y1 = l["bbox"]
            if pno > 1 and (x0 < 8 * MM or x1 > W - 8 * MM or y1 > H - 8 * MM):
                issues.append(f"쪽 가장자리 침범: {l['text'][:40]}")
        for i in range(len(L)):
            for j in range(i + 1, len(L)):
                w, h = inter(L[i]["bbox"], L[j]["bbox"])
                if w > 1 * MM and h > 0.25 * min(L[i]["size"], L[j]["size"]):
                    issues.append(f"글줄 겹침: 「{L[i]['text'][:24]}」 × 「{L[j]['text'][:24]}」")
        if pno > 1:
            for r in boxes_of(page):
                for l in L:
                    w, h = inter(l["bbox"], r)
                    if w > 0.5 * MM and h > 0.5 and not inside(l["bbox"], r):
                        issues.append(f"상자 경계 걸침: {l['text'][:40]}")
            for im in page.get_image_info():
                r = im["bbox"]
                if r[2] - r[0] > 200 * MM:
                    continue
                for l in L:
                    w, h = inter(l["bbox"], r)
                    if w > 0.8 * MM and h > 0.8 and not inside(l["bbox"], r, tol=0):
                        issues.append(f"그림 걸침: {l['text'][:40]}")
        dashes = sum(l["text"].count("—") for l in L)
        if dashes:
            issues.append(f"줄표(—) {dashes}개")
        sizes = [l["size"] for l in L]
        print(f"[{pno}쪽] 글줄 {len(L)} · 최소 {min(sizes):.1f}pt · 문제 {len(issues)}")
        for s in dict.fromkeys(issues):
            print("   -", s)
        total += len(issues)
    print(f"합계 {total}건 · {pdf.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
