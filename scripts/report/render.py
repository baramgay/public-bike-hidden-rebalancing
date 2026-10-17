"""PPTX → PDF(PowerPoint) → 쪽별 PNG, 내장 글꼴 점검. 사용: python render.py [pptx] [dpi]"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pptx = Path(sys.argv[1]) if len(sys.argv) > 1 else max((ROOT / "outputs" / "report").glob("*_분석보고서.pptx"), key=lambda p: p.stat().st_mtime)
    dpi = int(sys.argv[2]) if len(sys.argv) > 2 else 110
    pdf = pptx.with_suffix(".pdf")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "scripts" / "report" / "export_pdf.ps1"), str(pptx), str(pdf)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return r.returncode
    doc = fitz.open(pdf)
    out = pptx.parent / "render"
    out.mkdir(exist_ok=True)
    for old in out.glob("page-*.png"):
        old.unlink()
    fonts = set()
    for i, page in enumerate(doc, 1):
        page.get_pixmap(dpi=dpi).save(out / f"page-{i}.png")
        fonts |= {f[3].split("+")[-1] for f in page.get_fonts()}
    w, h = (v / 72 * 25.4 for v in doc[0].rect[2:])
    print(f"pages={len(doc)} size={w:.1f}x{h:.1f}mm fonts={sorted(fonts)}")
    print("\n".join(str(p) for p in sorted(out.glob("page-*.png"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
