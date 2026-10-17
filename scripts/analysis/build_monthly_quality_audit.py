"""Independent monthly coverage audit of the three completed raw trip files."""
import calendar
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle
import numpy as np


def main():
    root = Path(__file__).resolve().parents[2]
    processed = root / 'data/processed/quality_audit'
    output = root / 'outputs/quality_audit'
    processed.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    totals = {}
    for year in (2023, 2024, 2025):
        counts, dates = Counter(), set()
        path = root / f'data/raw/nubija_trips/nubija_trips_{year}.csv'
        with path.open(encoding='cp949', newline='') as stream:
            reader = csv.DictReader(stream)
            if '출발일' not in reader.fieldnames:
                raise ValueError(f'Missing departure-date column: {path.name}')
            for record in reader:
                date = datetime.strptime(record['출발일'], '%Y-%m-%d').date()
                if date.year != year:
                    raise ValueError(f'Date outside file year: {path.name}')
                counts[date.month] += 1
                dates.add(date)
        totals[str(year)] = sum(counts.values())
        for month in range(1, 13):
            expected_days = calendar.monthrange(year, month)[1]
            observed_days = sum(d.month == month for d in dates)
            rows.append({
                'year': year, 'month': month,
                'observed_records': counts[month],
                'observed_departure_dates': observed_days,
                'calendar_days': expected_days,
                'coverage_status': 'all_calendar_dates_present' if observed_days == expected_days else 'missing_departure_dates',
            })
    expected_totals = {'2023': 4066540, '2024': 4582332, '2025': 4419063}
    if totals != expected_totals:
        raise ValueError(f'Independent totals disagree: {totals}')
    missing = [r for r in rows if r['coverage_status'] != 'all_calendar_dates_present']
    if [(r['year'], r['month'], r['observed_records']) for r in missing] != [(2025, 7, 0)]:
        raise ValueError(f'Unexpected month coverage: {missing}')
    font_path = root / 'assets/fonts/NotoSansKR.ttf'
    if not font_path.is_file():
        raise FileNotFoundError('Missing assets/fonts/NotoSansKR.ttf; see assets/fonts/README.md')
    font_manager.fontManager.addfont(str(font_path))
    font_name = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams.update({'font.family': font_name, 'axes.unicode_minus': False})
    matrix = np.array([[r['observed_records'] / 10000 for r in rows if r['year'] == y] for y in (2023, 2024, 2025)], dtype=float)
    matrix[2, 6] = np.nan
    fig, ax = plt.subplots(figsize=(14, 5.2), dpi=160)
    fig.patch.set_facecolor('#FAFBFD')
    ax.set_facecolor('#FAFBFD')
    cmap = plt.get_cmap('YlGnBu').copy()
    cmap.set_bad('#EDF0F3')
    image = ax.imshow(np.ma.masked_invalid(matrix), cmap=cmap, vmin=0, vmax=np.nanmax(matrix), aspect='auto')
    ax.set_xticks(range(12), [f'{m}월' for m in range(1, 13)], fontsize=11)
    ax.set_yticks(range(3), ['2023년', '2024년', '2025년'], fontsize=12)
    ax.tick_params(length=0, pad=12)
    for y in range(3):
        for x in range(12):
            value = matrix[y, x]
            if np.isnan(value):
                ax.add_patch(Rectangle((x-.5, y-.5), 1, 1, fill=False, hatch='///', edgecolor='#A0A8B3', linewidth=0))
                label, color = '자료\n누락', '#3E4856'
            else:
                label = f'{value:.1f}'
                color = 'white' if value > np.nanmax(matrix)*.6 else '#102B43'
            ax.text(x, y, label, va='center', ha='center', color=color, fontsize=12, fontweight='bold')
    ax.set_xticks(np.arange(-.5, 12, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 3, 1), minor=True)
    ax.grid(which='minor', color='#FAFBFD', linewidth=5)
    ax.tick_params(which='minor', length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    colorbar = fig.colorbar(image, ax=ax, fraction=.025, pad=.025)
    colorbar.set_label('공개 대여 기록 (만 건)', fontsize=10)
    colorbar.outline.set_visible(False)
    fig.text(.07, .94, '2025년 7월은 이용 0건이 아니라, 공개 기록의 누락입니다', fontsize=19, fontweight='bold', color='#102B43')
    fig.text(.07, .865, '창원 누비자 공개 CSV 3개 · 출발일 기준 월별 기록 수 · 원본을 다시 읽어 독립 집계', fontsize=11, color='#536477')
    fig.text(.07, .095, '색과 숫자는 관측 기록 수를 나타냅니다. 날짜가 모두 존재해도 미공개 통행이 없다는 보장은 아닙니다.', fontsize=10, color='#3E4856')
    fig.text(.07, .045, f'출처: 공공데이터포털 경상남도 창원시 누비자 대여·반납 이력 (15126280) · 검증일 {datetime.now().astimezone().date().isoformat()}', fontsize=9, color='#536477')
    fig.subplots_adjust(left=.09, right=.92, top=.76, bottom=.23)
    audit = {'checked_at': datetime.now().astimezone().isoformat(), 'independent_totals': totals, 'missing_months': missing,
             'interpretation': 'Zero observed records in July 2025 are treated as missing source coverage, not zero demand. All-date presence does not prove all trips were disclosed.',
             'chart_units': '10,000 observed departure records', 'source_catalog': 'https://www.data.go.kr/data/15126280/fileData.do'}
    # Validate all inputs before staging outputs. A failed validation leaves prior artifacts intact.
    staged_csv = processed / 'monthly_departure_coverage.csv.partial'
    with staged_csv.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    staged_json = processed / 'monthly_departure_coverage.json.partial'
    staged_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    staged_png = output / 'monthly_departure_coverage.png.partial'
    staged_svg = output / 'monthly_departure_coverage.svg.partial'
    fig.savefig(staged_png, format='png', facecolor=fig.get_facecolor())
    fig.savefig(staged_svg, format='svg', facecolor=fig.get_facecolor())
    plt.close(fig)
    for temporary, final in [(staged_csv, processed / 'monthly_departure_coverage.csv'),
                             (staged_json, processed / 'monthly_departure_coverage.json'),
                             (staged_png, output / 'monthly_departure_coverage.png'),
                             (staged_svg, output / 'monthly_departure_coverage.svg')]:
        temporary.replace(final)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
