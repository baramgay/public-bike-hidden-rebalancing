"""PowerPoint PDF의 한글 낱말 사이 공백 복원. 사용: python pdf_text_spaces.py <pdf> (인자 없으면 자체 점검)

원인: PowerPoint는 한글(Identity-H 글꼴) 구간을 낱말마다 따로 놓고 공백 글리프를 생략한다(글꼴·lang·eaLnBrk·NBSP와 무관).
화면은 같지만 간격으로 공백을 추정하지 않는 추출기(MuPDF 등)·뷰어에서 복사하면 띄어쓰기가 사라진다.
해결: 내용 스트림의 글자 표시 연산자(TJ/Tj)와 MuPDF 텍스트 추적 span이 1:1인 쪽에서, 같은 기준선의 다음 span과
간격이 글자 크기의 12% 이상(실측: 낱말 안 분할 ≈0, 공백 ≥0.18)이면 그 낱말 바로 뒤에 공백 글자를
렌더 모드 3(보이지 않음)으로 넣는다. 공백 글꼴은 그 쪽에 이미 있는 Pretendard 영문(WinAnsi) 글꼴을 써서 PDF 글꼴 목록을
Pretendard로 유지하고, 없을 때만 Base-14 Helvetica를 더한다. 공백 폭은 가로 배율(Tz)로 실제 간격에 맞춰, 간격으로 공백을 추정하는 추출기
(pdfminer 등)에서 이중 공백이 생기지 않게 한다. 화면·인쇄는 그대로이고, 이미 공백이 있는 곳은 건드리지 않아 다시 실행해도 같다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fitz

GAP = 0.12          # 공백으로 보는 최소 간격(글자 크기 대비)
SAME_LINE = 0.2     # 같은 기준선 허용 차이(글자 크기 대비)
WIDE = 0.6          # 이보다 넓은 간격(표 칸·단 사이)은 간격 폭으로 늘리지 않고 보통 공백 폭으로 둔다(선택 영역·배치 점검이 칸을 넘지 않게)
HELV = (b"helv", 0.278)   # 대체 공백 글꼴(Base-14 Helvetica, 공백 폭 278/1000 em)
WS, DELIM = b" \t\r\n\f\x00", b"()<>[]{}/%"


def ops(c: bytes):
    """내용 스트림의 연산자를 (이름, 피연산자, 끝 위치)로 차례대로 낸다. 인라인 이미지(BI)는 ValueError."""
    i, n, args = 0, len(c), []
    while i < n:
        ch = c[i:i + 1]
        if ch in WS:
            i += 1
        elif ch == b"%":
            while i < n and c[i:i + 1] not in b"\r\n":
                i += 1
        elif ch == b"(":                                  # 문자열: 괄호 중첩·역슬래시 처리
            j, depth = i + 1, 1
            while depth:
                b = c[j:j + 1]
                if b == b"\\":
                    j += 1
                elif b == b"(":
                    depth += 1
                elif b == b")":
                    depth -= 1
                j += 1
            args.append(c[i:j]); i = j
        elif c[i:i + 2] in (b"<<", b">>"):
            i += 2
        elif ch == b"<":
            j = c.index(b">", i) + 1
            args.append(c[i:j]); i = j
        elif ch in b"[]{}":
            i += 1
        else:
            j = i + 1
            while j < n and c[j:j + 1] not in WS and c[j:j + 1] not in DELIM:
                j += 1
            tok = c[i:j]
            if ch == b"/" or tok[:1] in b"+-.0123456789":
                args.append(tok)
            elif tok in (b"true", b"false", b"null"):
                args.append(tok)
            else:
                if tok == b"BI":
                    raise ValueError("inline image")
                yield tok, args, j
                args = []
            i = j


def insertions(c: bytes, spans: list, sp: tuple[bytes, float] = HELV) -> list[tuple[int, bytes]] | None:
    """공백을 넣을 (스트림 위치, 넣을 바이트) 목록. 연산자와 span 수가 다르면 None."""
    shows, stack = [], []
    state = {b"Tf": [b"", b"0"], b"Tr": b"0", b"Tc": b"0", b"Tw": b"0", b"Tz": b"100"}   # 글자 상태(q/Q로 저장·복원)
    for op, args, end in ops(c):
        if op == b"q":
            stack.append(dict(state))
        elif op == b"Q" and stack:
            state = stack.pop()
        elif op == b"Tf" and len(args) >= 2:
            state[op] = args[-2:]
        elif op in state and args:
            state[op] = args[-1]
        elif op in (b"TJ", b"Tj", b"'", b'"'):
            shows.append((end, dict(state)))
    if len(shows) != len(spans):
        return None
    out = []
    for (end, st), a, b in zip(shows, spans, spans[1:] + [None]):
        (font, size), tr, tz = st[b"Tf"], st[b"Tr"], st[b"Tz"]
        if b is None or not font or not a["chars"] or not b["chars"] or a["dir"] != (1.0, 0.0) or b["dir"] != (1.0, 0.0):
            continue
        last, first = a["chars"][-1], b["chars"][0]
        s = max(a["size"], b["size"])
        if chr(last[0]).isspace() or chr(first[0]).isspace() or abs(last[2][1] - first[2][1]) > SAME_LINE * s:
            continue
        gap = first[3][0] - last[3][2]
        if gap >= GAP * s:
            fs = float(size)
            adv = sp[1] * fs + float(st[b"Tc"]) + float(st[b"Tw"])             # 공백 글자의 실제 전진 폭
            if fs <= 0 or adv <= 0:
                continue
            scale = a["size"] / fs                                            # 글자 공간 → 쪽 공간 배율
            tzv = 100 * gap / scale / adv if gap <= WIDE * s else 100.0
            out.append((end, b" /%s %s Tf 3 Tr %.2f Tz ( ) Tj %s Tz %s Tr %s %s Tf"
                        % (sp[0], size, tzv, tz, tr, font, size)))
    return out


def space_font(doc, page) -> tuple[bytes, float] | None:
    """쪽 자원 중 공백(코드 32) 폭이 있는 WinAnsi 단순 글꼴의 (자원 이름, 공백 폭 em)."""
    for xref, _, typ, _, ref, enc in page.get_fonts():
        if enc != "WinAnsiEncoding" or typ not in ("TrueType", "Type1"):
            continue
        fc, w = doc.xref_get_key(xref, "FirstChar"), doc.xref_get_key(xref, "Widths")
        if fc[0] != "int" or int(fc[1]) > 32 or w[0] not in ("array", "xref"):
            continue
        arr = doc.xref_object(int(w[1].split()[0])) if w[0] == "xref" else w[1]
        ws = arr.strip().strip("[]").split()
        k = 32 - int(fc[1])
        if k < len(ws) and float(ws[k]) > 0:
            return ref.encode(), float(ws[k]) / 1000
    return None


def fix(pdf: Path) -> int:
    """pdf를 제자리에서 고친다. 넣은 공백 수를 돌려준다."""
    doc = fitz.open(pdf)
    total = 0
    for page in doc:
        xrefs = page.get_contents()
        c = page.read_contents()
        try:
            sp = space_font(doc, page)
            ins = insertions(c, page.get_texttrace(), sp or HELV) if len(xrefs) == 1 else None
        except ValueError:
            ins = None
        if ins is None:
            print(f"경고: {page.number + 1}쪽은 글자 연산자와 추적 span이 맞지 않아 공백을 넣지 않음", file=sys.stderr)
            continue
        if not ins:
            continue
        if not sp:
            page.insert_font(fontname=HELV[0].decode())
        parts, prev = [], 0
        for pos, b in ins:
            parts += [c[prev:pos], b]
            prev = pos
        doc.update_stream(xrefs[0], b"".join(parts) + c[prev:])
        total += len(ins)
    if total:
        tmp = pdf.with_name(pdf.stem + ".spaces.tmp.pdf")
        doc.save(tmp, garbage=1, deflate=True, use_objstms=1)   # 객체 스트림: 원본(PowerPoint)보다 작게
        doc.close()
        os.replace(tmp, pdf)
    else:
        doc.close()
    return total


def _selftest() -> None:
    c = b"q BT /F2 9.96 Tf 1 0 0 1 10 10 Tm [<2040>] TJ ET Q q BT /F1 9 Tf (a\\)b(c)) Tj ET Q"
    assert [o for o, _, _ in ops(c)] == [b"q", b"BT", b"Tf", b"Tm", b"TJ", b"ET", b"Q", b"q", b"BT", b"Tf", b"Tj", b"ET", b"Q"]
    sp = lambda x0, x1, ch: {"dir": (1.0, 0.0), "size": 10.0, "chars": [(ord(ch), 0, (x0, 0.0), (x0, -8, x1, 2))]}
    ins = insertions(c, [sp(0, 10, "가"), sp(12.5, 20, "나")])          # 간격 2.5 = 0.25em → 공백
    assert len(ins) == 1 and ins[0][1].endswith(b"/F2 9.96 Tf") and c[:ins[0][0]].endswith(b"TJ")
    assert insertions(c, [sp(0, 10, "A"), sp(10, 20, "와")]) == []     # 붙은 글자(글꼴만 바뀜) → 그대로
    assert insertions(c, [sp(0, 10, "가")]) is None                     # 개수 불일치 → 손대지 않음
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _selftest()
    else:
        print(f"공백 {fix(Path(sys.argv[1]))}개 삽입")
