"""Build a public-data proximity audit figure; no map/API calls."""
from pathlib import Path
import csv, hashlib, json, platform, statistics
from datetime import datetime, timezone
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / 'data/processed/accessibility_qa'
OUT = ROOT / 'outputs/accessibility_audit'
FONT = ROOT / 'assets/fonts/NotoSansKR.ttf'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with (INPUT / 'station_2025_active_stop_accessibility.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    with (INPUT / 'district_summary.csv').open(encoding='utf-8-sig', newline='') as f:
        summaries = list(csv.DictReader(f))
    distances = np.array([float(r['nearest_stop_straight_m']) for r in rows])
    alternate = np.array([float(r['nearest_excluding_literal_virtual_name_m']) for r in rows])
    if len({r['터미널번호'] for r in rows}) != len(rows):
        raise ValueError('Duplicate station ID')
    if not np.isfinite(distances).all() or (distances < 0).any():
        raise ValueError('Invalid distance')
    n = len(rows)
    close = int((distances <= 300).sum())
    close_alt = int((alternate <= 300).sum())
    median = float(np.median(distances))
    groups = []
    for s in summaries:
        subset = [r for r in rows if r['구'] == s['district']]
        ds = [float(r['nearest_stop_straight_m']) for r in subset]
        count = sum(d <= 300 for d in ds)
        med = statistics.median(ds)
        assert len(subset) == int(s['active_stations'])
        assert count == int(s['stations_with_stop_within_300m'])
        assert abs(med - float(s['nearest_straight_median_m'])) < 1e-5
        groups.append(dict(district=s['district'], n=len(subset), within_300m=count, median_m=med))
    assert sum(g['n'] for g in groups) == n
    assert sum(g['within_300m'] for g in groups) == close
    assert (n, close) == (454, 435), 'Input changed: review the figure narrative'
    font_manager.fontManager.addfont(FONT)
    plt.rcParams.update({'font.family': font_manager.FontProperties(fname=FONT).get_name(),
                         'font.size': 9.5, 'axes.unicode_minus': False, 'svg.fonttype': 'path'})
    navy, blue, orange, gray = '#172B3A', '#0072B2', '#D55E00', '#E5E7EB'
    fig = plt.figure(figsize=(178/25.4, 225/25.4), facecolor='white')
    texts = []
    def label(x, y, text, size=9.5, color=navy, **kw):
        obj = fig.text(x, y, text, fontsize=size, color=color, **kw)
        texts.append(obj)
        return obj
    label(.04, .963, '정류장은 가까운데,', 16, weight='bold')
    label(.04, .931, '생활 이동도 연결되어 있을까?', 16, weight='bold')
    label(.04, .895, '관측 분석  |  2025년 사용함 거점의 정류소 근접성', 9.5)
    label(.04, .823, f'{close/n*100:.1f}%', 30, color=blue, weight='bold')
    label(.39, .850, f'{close:,} / {n:,}개 거점', 13, weight='bold')
    label(.39, .824, '최근접 정류소까지 직선 300m 이내', 10.5)
    label(.04, .774, f'최근접 거리 중앙값 {median:.2f}m', 11, weight='bold')
    label(.04, .744, '전체 거점을 가까운 순서로 놓으면', 10.5)
    ax = fig.add_axes([.12, .574, .83, .145])
    x = np.arange(1, n + 1)
    ax.fill_between(x, 0, distances[np.argsort(distances)], color=blue, alpha=.12)
    ax.plot(x, np.sort(distances), color=blue, linewidth=1.8)
    ax.axhline(300, color=orange, linewidth=1.2, linestyle='--')
    ax.text(n*.43, 330, '진단 문턱 300m', fontsize=9.5, color=orange)
    ax.set_xlim(1,n); ax.set_ylim(0, max(1000, np.ceil(distances.max()/100)*100))
    ax.set_xticks([1, n//2, n]); ax.set_yticks([0,300,1000])
    ax.set_xlabel('가까운 순서의 거점 (개)', fontsize=9.5, labelpad=3)
    ax.set_ylabel('직선거리 (m)', fontsize=9.5, labelpad=3)
    ax.spines[['top','right']].set_visible(False)
    ax.spines[['bottom','left']].set_color('#9AA4AB')
    ax.tick_params(labelsize=9.5, length=2, colors=navy)
    label(.04,.503,'구별로도 가까운 거점이 많지만, 거리의 분포는 다르다',10.5,weight='bold')
    label(.04,.468,'구 · 활동 거점',9.5)
    label(.34,.468,'300m 이내 비율 (회색: 초과)',9.5)
    label(.96,.468,'중앙값',9.5,ha='right')
    for i,g in enumerate(groups):
        y=.431-i*.044
        label(.04,y,f"{g['district']} · {g['n']}개",9.5)
        bar=fig.add_axes([.34,y-.002,.32,.015])
        p=g['within_300m']/g['n']
        bar.barh([0],[1],color=gray,height=.9)
        bar.barh([0],[p],color=blue,height=.9)
        bar.set_xlim(0,1);bar.set_ylim(-.5,.5);bar.axis('off')
        label(.69,y,f'{100*p:.1f}%',9.5)
        label(.96,y,f"{g['median_m']:.1f}m",9.5,ha='right')
    label(.04,.211,'가까움은 연결 서비스와 같지 않다.',11.5,weight='bold')
    label(.04,.184,'다음 질문: 보행 경로·버스 운행·목적지 연결은 어떠한가?',10)
    caption = [
        f'분모: 2025년 시트의 사용함 {n}거점. 전체 주민의 취약도를 측정하지 않음.',
        '기준: 두 자료명 2025-12-31. 연중 운영 변화·현재 운영 상태는 미확인.',
        '거리: 구면 직선거리(300m 이하). 보행시간·배차·실제환승·재고는 미측정.',
        f'민감도: 정류소명에 “가상” 포함 행 제외 시 {close_alt}/{n}개 ({100*close_alt/n:.1f}%).',
        '출처: 창원시 누비자 터미널·버스정류소 위치정보 / 공공데이터포털',
        'data.go.kr/data/15000545/fileData.do',
        'data.go.kr/data/15037805/fileData.do',
        '가상 명칭 제외는 실제 승하차 가능 시설 확인을 뜻하지 않음.'
    ]
    for i,line in enumerate(caption): label(.04,.157-i*.020,line,9)
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    for t in texts:
        bb=t.get_window_extent(renderer)
        if bb.x0 < 0 or bb.x1 > fig.bbox.width+1 or bb.y0 < 0 or bb.y1 > fig.bbox.height+1:
            raise ValueError(f'Text outside canvas: {t.get_text()}')
    png=OUT/'accessibility_proximity.png'; svg=OUT/'accessibility_proximity.svg'
    fig.savefig(png,dpi=300,facecolor='white')
    fig.savefig(svg,facecolor='white')
    plt.close(fig)
    metrics=dict(stations=n,within_300m=close,share_pct=100*close/n,median_m=median,
                 excluding_literal_virtual_within_300m=close_alt,districts=groups)
    (OUT/'accessibility_proximity_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    def record(p): return dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    manifest={'generated_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
              'matplotlib':matplotlib.__version__,'numpy':np.__version__,
              'inputs':[record(INPUT/name) for name in ['station_2025_active_stop_accessibility.csv','district_summary.csv']],
              'font':record(FONT),'outputs':[record(png),record(svg)],'metrics':metrics}
    (OUT/'accessibility_proximity_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'accessibility_proximity_metadata.md').write_text(
        '# 정류소 근접성 대표 인포그래픽\n\n'
        '재현: `python scripts/analysis/build_accessibility_infographic.py`\n\n'
        'PNG 300dpi·SVG, 최종 폭178mm/높이225mm. NotoSansKR.ttf 직접 등록, assets/fonts/OFL.txt 참조. '
        '본문 라벨9.5pt 이상·출처9pt, SVG 글리프는 재현성을 위해 경로화했다. 원본CSV는 변경하지 않았다. '
        '외부 지도·API·생성형 이미지·개인자료 없음. 원자료 출처·이용조건은 data/metadata/stations_operations_transit.md에 기록했다.\n\n'
        '검산: 거점ID유일성·거리유효성·구별분모/300m개수/중앙값을 독립 재집계하여 district_summary.csv와 비교했다. '
        '그림 숫자는 CSV에서 계산하며 454/435는 입력 변경 감지용 검산 조건에만 사용했다. '
        '텍스트 캔버스 이탈 검사 통과. PNG 시각검토 결과는 후속 검토 문단에 기록한다.\n\n'
        '주의: 기존 운영거점만 측정, 전체주민취약도·버스노선공급·실제환승·보행경로·재고를 측정하지 않는다. '
        '두 원자료명 기준2025-12-31, 정확한 연중 운영 변화는 미확인. 가상은 이름 문자열 필터일 뿐 실제 시설 검증 아님. '
        '구면거리 계산·좌표 가정은 scripts/collection/accessibility_join_qa.py 참조.\n\n'
        '크기·SHA256·버전·실행시각·구별 지표는 accessibility_proximity_manifest.json 및 metrics.json에 보존한다.\n',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False))

if __name__ == '__main__': main()

