"""Bounded, hidden PowerPoint proof. This does not build the final report."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/design_preflight"
SOURCE = ROOT / "data/processed/accessibility_qa/station_2025_active_stop_accessibility.csv"
FONT = "Malgun Gothic"
PPTX = OUT / "a4_layout_test.pptx"
PDF = OUT / "a4_layout_test.pdf"


def source_summary():
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8-sig")))
    total = len(rows)
    within = sum(float(row["nearest_stop_straight_m"]) <= 300 for row in rows)
    result = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "total": total,
        "within_300m": within,
        "over_300m": total - within,
        "within_percent": round(100 * within / total, 1),
        "over_percent": round(100 * (total - within) / total, 1),
    }
    if (total, within, result["within_percent"]) != (454, 435, 95.8):
        raise ValueError(f"Source changed: {result}")
    return result


def office_processes():
    import psutil
    return {p.pid for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() in {"powerpnt.exe", "excel.exe"}}


def worker(before):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    deck = None
    own_pid = None
    summary = source_summary()
    result = {"source_summary": summary, "font": FONT}
    mm = lambda value: value * 72 / 25.4
    rgb = lambda h: int(h[0:2], 16) + (int(h[2:4], 16) << 8) + (int(h[4:6], 16) << 16)
    ink = rgb("172B3A")
    muted = rgb("4C5E6A")
    blue = rgb("0072B2")
    grey = rgb("D2D8DD")
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        import psutil
        new_powerpoint = {p.pid for p in psutil.process_iter(["name"])
                          if (p.info["name"] or "").lower() == "powerpnt.exe"} - before
        own_pid = next(iter(new_powerpoint)) if len(new_powerpoint) == 1 else None
        (OUT / "owned_processes.json").write_text(json.dumps([own_pid] if own_pid else []), encoding="utf-8")
        result.update({"powerpoint_version": app.Version, "powerpoint_pid": own_pid,
                       "own_application_process": own_pid is not None})
        app.DisplayAlerts = 1
        deck = app.Presentations.Add(WithWindow=False)
        deck.PageSetup.SlideWidth = mm(210)
        deck.PageSetup.SlideHeight = mm(297)
        slide = deck.Slides.Add(1, 12)
        slide.FollowMasterBackground = False
        slide.Background.Fill.ForeColor.RGB = rgb("FFFFFF")

        def text(value, x, y, w, h, size=11, bold=False, color=ink):
            shape = slide.Shapes.AddTextbox(1, mm(x), mm(y), mm(w), mm(h))
            shape.TextFrame.MarginLeft = 0
            shape.TextFrame.MarginRight = 0
            shape.TextFrame.MarginTop = 0
            shape.TextFrame.MarginBottom = 0
            shape.TextFrame.WordWrap = -1
            shape.TextFrame.AutoSize = 0
            tr = shape.TextFrame.TextRange
            tr.Text = value
            tr.Font.Name = FONT
            tr.Font.NameFarEast = FONT
            tr.Font.NameAscii = FONT
            tr.Font.NameOther = FONT
            shape.TextFrame2.TextRange.Font.Name = FONT
            shape.TextFrame2.TextRange.Font.NameFarEast = FONT
            tr.Font.Size = size
            tr.Font.Bold = -1 if bold else 0
            tr.Font.Color.RGB = color
            tr.ParagraphFormat.SpaceAfter = 0
            tr.ParagraphFormat.SpaceBefore = 0
            tr.ParagraphFormat.SpaceWithin = 1.35
            return shape

        text("A4 조판·출력 시험 / 최종 분석보고서 아님", 16, 16, 178, 6, 9.5, color=muted)
        text("버스정류소와의\n직선 근접성", 16, 28, 178, 30, 24, True)
        text("435 / 454", 16, 70, 178, 20, 38, True, blue)
        text("활동 거점 중 버스정류소 직선 300m 이내", 16, 94, 178, 8, 12, True)
        text("95.8%   기준연도 2025", 16, 105, 178, 7, 11, color=muted)

        text("검증한 관측 집계", 16, 131, 178, 8, 12, True)
        text("정류소와 가까운 거점의 수를 나타낸다. 보행 연결, 운행 빈도·실제\n환승 또는 자전거 가용성을 입증하는 수치로 해석할 수 없다.",
             16, 190, 178, 19, 10.5)

        table = slide.Shapes.AddTable(4, 3, mm(16), mm(145), mm(178), mm(31)).Table
        table.Columns(1).Width = mm(94)
        table.Columns(2).Width = mm(42)
        table.Columns(3).Width = mm(42)
        values = [
            ["직선거리 기준", "거점 수(개)", "비율(%)"],
            ["300m 이내", str(summary["within_300m"]), f"{summary['within_percent']:.1f}"],
            ["300m 초과", str(summary["over_300m"]), f"{summary['over_percent']:.1f}"],
            ["전체 활동 거점", str(summary["total"]), "100.0"],
        ]
        for ri, row in enumerate(values, 1):
            for ci, value in enumerate(row, 1):
                cell = table.Cell(ri, ci)
                cell.Shape.Fill.ForeColor.RGB = rgb("EDF2F5") if ri == 1 else rgb("FFFFFF")
                tf = cell.Shape.TextFrame
                tf.MarginLeft, tf.MarginRight = mm(2), mm(2)
                tf.MarginTop, tf.MarginBottom = mm(0.5), mm(0.5)
                tf.VerticalAnchor = 3
                tr = tf.TextRange
                tr.Text = value
                tr.Font.Name = FONT
                tr.Font.NameFarEast = FONT
                tr.Font.NameAscii = FONT
                tr.Font.NameOther = FONT
                cell.Shape.TextFrame2.TextRange.Font.Name = FONT
                cell.Shape.TextFrame2.TextRange.Font.NameFarEast = FONT
                tr.Font.Size = 9.5
                tr.Font.Bold = -1 if ri == 1 else 0
                tr.Font.Color.RGB = ink
                tr.ParagraphFormat.Alignment = 1 if ci == 1 else 3
                for edge in (1, 2, 3, 4):
                    cell.Borders(edge).ForeColor.RGB = grey
                    cell.Borders(edge).Weight = 0.4
        text("출처: 검증한 접근성 집계 CSV, 454행. 원자료의 직선거리 300m 기준 재집계.\n"
             "검수 범위: 한글 글꼴·편집 가능한 표와 텍스트·A4 PDF 출력. 정책 효과 검수는 제외.",
             16, 258, 178, 14, 9, color=muted)
        text("LAYOUT TEST  01", 16, 278, 178, 5, 9, color=muted)
        slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = (
            "Layout proof only, not a final report. Source: " + summary["source"] +
            "\nSHA256: " + summary["sha256"] +
            "\nMethod: nearest_stop_straight_m <= 300; count rows. "
            "435/454 = 95.8149779735683%, displayed 95.8%. "
            "No policy result or actual transfer claim."
        )
        deck.SaveAs(str(PPTX), 24)
        result["font_property_readback"] = {
            key: getattr(slide.Shapes(1).TextFrame.TextRange.Font, key)
            for key in ("Name", "NameFarEast", "NameAscii", "NameOther")
        }
        deck.SaveAs(str(PDF), 32)
        slide.Export(str(OUT / "powerpoint_page.png"), "PNG", 1240, 1754)
        result.update({"slides": deck.Slides.Count, "native_charts": 0, "native_tables": 1,
                       "native_chart_limitation": "PowerPoint AddChart/AddChart2: HRESULT -2147467259",
                       "pptx": str(PPTX), "pdf": str(PDF), "status": "exported"})
        (OUT / "worker_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        if deck is not None:
            deck.Close()
        if app is not None and own_pid is not None:
            app.Quit()
        pythoncom.CoUninitialize()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = source_summary()
    if "--worker" in sys.argv:
        worker(set(json.loads(sys.argv[-1])))
        return
    before = office_processes()
    worker_result = OUT / "worker_result.json"
    if worker_result.exists():
        worker_result.unlink()
    (OUT / "owned_processes.json").write_text("[]", encoding="utf-8")
    result = {"source_summary": summary, "timeout_seconds": 30}
    try:
        completed = subprocess.run(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--worker", json.dumps(sorted(before))],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        result.update({"returncode": completed.returncode, "stdout": completed.stdout,
                       "stderr": completed.stderr})
    except subprocess.TimeoutExpired as exc:
        result.update({"status": "timeout", "error": str(exc)})
    finally:
        import psutil
        # Only the exact PowerPoint PID recorded by this worker may be terminated.
        owned = json.loads((OUT / "owned_processes.json").read_text(encoding="utf-8"))
        for pid in set(owned) - before:
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass
    if worker_result.exists():
        result["export_result"] = json.loads(worker_result.read_text(encoding="utf-8"))
    (OUT / "export_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
