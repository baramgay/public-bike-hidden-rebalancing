"""창원시의회 회의록에서 '누비자'·'공영자전거' 언급 발언 수집(공개 페이지만, 로그인·캡차 없음).

단계: 1) 회의록 색인어검색으로 회의 목록 확보 -> 2) 대상 기간 회의록 원문 HTML 저장(기존 파일 덮어쓰기 금지)
      -> 3) 원문을 발언 단위로 파싱해 CSV 생성.
실행(프로젝트 루트): python scripts/collection/civic_text_collect.py
  --parse-only  네트워크 없이 이미 받은 원문으로 CSV만 다시 만든다.
  --selftest    네트워크 없이 파서 자체 점검.
요청 간격 2.5초(지시 기준 2초 이상), robots.txt 확인, 외부에 아무것도 제출하지 않는다(검색어 조회만).
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
BASE = 'https://council.changwon.go.kr'
RAW = ROOT / 'data/raw/civic_text/council_minutes'
OUT = ROOT / 'data/processed/civic_text/nubija_utterances.csv'
MANIFEST = RAW / '_manifest.csv'
UA = 'nubija-civic-text-research/1.0 (public council minutes, polite crawler)'
GAP = 2.5                       # 요청 간 최소 간격(초)
KST = timezone(timedelta(hours=9))
TERMS = ('누비자', '공영자전거')
GENERATIONS = ('3', '4', '5')   # 3대(2018.7~2022.6), 4대(2022.7~2026.6), 5대(2026.7~). 2020-01-01 이후가 걸치는 대수
START, END = '2020-01-01', '2026-10-17'
HIT = re.compile('|'.join(TERMS))
FIELDS = ['doc_id', '회의일', '회의명', '회차', '발언자 직위', '발언 원문', '출처 URL', '수집시각']
MANIFEST_FIELDS = ['mnts_id', 'file', 'title', 'meeting_date', 'provisional', 'url', 'fetched_at', 'bytes', 'sha256', 'search_terms']
TITLE = re.compile(r'(?:\[임시회의록\])?\s*(제\d+회)\s+(제\d+[차일])\s+(.+?)\s*\((\d{4})\.(\d{2})\.(\d{2})[^)]*\)\s*$')


def norm(text):
    return re.sub(r'\s+', ' ', text or '').strip()


class Client:
    """요청 간격·robots.txt를 지키는 얇은 requests 래퍼."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers['User-Agent'] = UA
        self.last = 0.0
        self.robots = None
        robots = robotparser.RobotFileParser()
        robots.parse(self.get('/robots.txt').text.splitlines())
        self.robots = robots

    def get(self, path, method='GET', **kw):
        if self.robots is not None and not self.robots.can_fetch(UA, BASE + path):
            raise PermissionError(f'robots.txt 불허: {path}')
        err = ''
        for attempt in range(4):
            time.sleep(max(0.0, GAP - (time.monotonic() - self.last)))
            try:
                r = self.s.request(method, BASE + path, timeout=(15, 120), **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                err = type(e).__name__
            else:
                err = f'HTTP {r.status_code}'
                if r.status_code == 200:
                    self.last = time.monotonic()
                    return r
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
            self.last = time.monotonic()
            time.sleep(GAP * 4 * (attempt + 1))       # 10, 20, 30초 쉬고 다시 시도
        raise RuntimeError(f'요청 실패(4회, {err}): {path}')


def parse_list_page(page):
    """검색 결과 한 쪽 -> ([hit...], totalCnt 또는 None, 다음쪽 링크 {쪽번호: 경로})"""
    soup = BeautifulSoup(page, 'html.parser')
    hits = []
    for li in soup.select('div.msr_list li'):
        subject, link = li.select_one('span.subject'), li.select_one('span.keywordsubject a')
        mnts_id = re.search(r'mntsId=(\d+)', link['href']).group(1)
        title = norm(subject.get_text())
        date = re.search(r'\((\d{4})\.(\d{2})\.(\d{2})', title)
        hits.append({'mnts_id': mnts_id, 'title': title, 'date': '-'.join(date.groups()),
                     'provisional': subject.select_one('b.temporarily') is not None})
    pages, total = {}, None
    for a in soup.select('#pagingNew a[href*="pageNo="]'):
        pages[int(re.search(r'pageNo=(\d+)', a['href']).group(1))] = a['href']
        total = int(re.search(r'totalCnt=(\d+)', a['href']).group(1))
    return hits, total, pages


def search(client, gen, term):
    """색인어검색(회의구분·회수 전체). 쪽 경계에서 1건이 겹치므로 회의 ID로 중복 제거하고 totalCnt와 대조한다."""
    r = client.get('/svc/cms/mnts/MntsKeywordSearch.do', 'POST',
                   data={'var01': gen, 'var02': '', 'var03': '', 'var04': '', 'var07': term})
    hits, total, pages = parse_list_page(r.text)
    seen = {1}
    while True:
        todo = sorted(n for n in pages if n not in seen)
        if not todo:
            break
        seen.add(todo[0])
        more, total2, pages2 = parse_list_page(client.get(pages[todo[0]]).text)
        hits += more
        pages.update(pages2)
        total = total2 or total
    unique = {h['mnts_id']: h for h in hits}
    if total is not None and len(unique) != total:
        raise RuntimeError(f'검색 결과 누락 의심 {gen}대 {term}: 수집 {len(unique)} / 표시 {total}')
    return list(unique.values()), total


def collect_hits(client):
    """대수×검색어 전체 검색 후 대상 기간만 회의 ID 기준으로 합친다. 검색 건수 요약도 반환."""
    docs, summary = {}, []
    for gen in GENERATIONS:
        for term in TERMS:
            found, total = search(client, gen, term)
            inside = [h for h in found if START <= h['date'] <= END]
            summary.append({'대수': gen, '검색어': term, '검색결과': len(found), '표시건수': total, '대상기간': len(inside)})
            print(f'[검색] {gen}대 {term}: 전체 {len(found)}건 중 대상기간 {len(inside)}건', flush=True)
            for h in inside:
                docs.setdefault(h['mnts_id'], {**h, 'terms': set()})['terms'].add(term)
    return docs, summary


def split_title(title, provisional):
    """'제149회 제2차 본회의(2026.01.26 월요일)' -> (회의일, 회차, 회의명). 형식이 다르면 예외."""
    m = TITLE.match(title)
    if not m:
        raise ValueError(f'회의 제목 형식 불일치: {title}')
    session, sitting, body, y, mo, d = m.groups()
    name = f'{session} {sitting} {body}'
    return f'{y}-{mo}-{d}', f'{session} {sitting}', ('[임시회의록] ' if provisional else '') + name


def raw_name(h):
    date, _, name = split_title(h['title'], False)
    name = name.replace('[임시회의록] ', '')
    return f"{date.replace('-', '')}_{name.replace(' ', '_')}_mnts{h['mnts_id']}{'_임시' if h['provisional'] else ''}.html"


def validate_page(raw, mnts_id):
    text = raw.decode('utf-8')
    if 'id="minutesContentArea"' not in text or not text.rstrip().endswith('</html>'):
        raise ValueError(f'회의록 본문 구조 불일치(잘림·오류 페이지 의심): {mnts_id}')
    if f'id="mntsId" value="{mnts_id}"' not in text:
        raise ValueError(f'회의 ID 불일치: {mnts_id}')
    return text


def save_new(client, h):
    """원문 저장. 같은 회의의 확정본이 있거나(또는 임시본끼리) 이미 있으면 건너뛴다. 기존 파일은 절대 덮어쓰지 않는다."""
    target = RAW / raw_name(h)
    same = list(RAW.glob(raw_name(h).rsplit('_mnts', 1)[0] + '_mnts*.html'))   # 같은 회의(날짜+회의명)의 저장본
    if any(not p.stem.endswith('_임시') for p in same) or (h['provisional'] and same):
        return None
    r = client.get('/cms/mntsViewer.do', params={'mntsId': h['mnts_id']})
    validate_page(r.content, h['mnts_id'])
    RAW.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial')
    partial.write_bytes(r.content)            # 이 확장자의 임시 파일은 우리 것이므로 재시도 때 덮어써도 된다
    if target.exists():
        raise FileExistsError(f'수집 중 최종 파일 생성됨, 덮어쓰기 금지: {target.name}')
    os.replace(partial, target)
    row = {'mnts_id': h['mnts_id'], 'file': target.name, 'title': h['title'], 'meeting_date': h['date'],
           'provisional': int(h['provisional']), 'url': f"{BASE}/cms/mntsViewer.do?mntsId={h['mnts_id']}",
           'fetched_at': datetime.now(KST).isoformat(timespec='seconds'), 'bytes': len(r.content),
           'sha256': hashlib.sha256(r.content).hexdigest(), 'search_terms': ';'.join(sorted(h['terms']))}
    is_new = not MANIFEST.exists()
    with MANIFEST.open('a', encoding='utf-8-sig', newline='') as f:   # 추가만 한다(이력 보존)
        w = csv.DictWriter(f, MANIFEST_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow(row)
    return row


TITLE_WORDS = {'이사장', '상임이사', '본부장', '국장', '과장', '실장', '팀장', '소장', '원장', '단장', '부시장', '시장', '구청장', '처장', '센터장', '담당관', '지점장'}
TITLE_END = re.compile(r'(장|관|원|사|대행|대리|후보자|팀|실|과|국|단|부|처|소)$')


def looks_like_title(token):
    """이름 없이 직함만 적힌 발언자 표시를 가려낸다(예: '창원경륜공단 공영자전거팀장'). 4글자 이상이 직함 어미로 끝나면 직함."""
    return token in TITLE_WORDS or (len(token) >= 4 and bool(TITLE_END.search(token)))


def split_label(span):
    """발언자 표시 span -> (직위, 이름). 의원은 이름만 별도 span, 공무원은 '소속 직위 이름' 한 덩어리(이름이 없을 수도 있음)."""
    full = norm(span.get_text(' ')).replace('○', '').strip()
    inner = span.find('span')
    if inner is not None:
        name = norm(inner.get_text())
        return norm(full.replace(name, '', 1)) or full, name
    parts = full.split(' ')
    if len(parts) > 1 and not looks_like_title(parts[-1]):
        return ' '.join(parts[:-1]), parts[-1]
    return full, ''


def parse_minutes(text):
    """원문 HTML -> (제목, 발언 목록, 본문 밖 언급 수). 발언 = 발언자 한 번의 연속 말(SPKR 블록)."""
    soup = BeautifulSoup(text, 'html.parser')
    title = norm(soup.select_one('#minutesTop h3').get_text())
    area = soup.find(id='minutesContentArea')
    total = len(HIT.findall(area.get_text(' ')))        # 발언자 표시를 떼기 전에 센다
    anchors = {a['name'] for a in area.find_all('a', attrs={'name': True})}
    turns = []
    for no, div in enumerate(area.find_all('div', class_=re.compile(r'^SPKR')), 1):
        label = div.select_one('span.spkrbld')
        if label is None:
            raise ValueError(f'발언자 표시 없는 발언 블록: {div.get("class")}')
        position, name = split_label(label)
        label_text = label.get_text(' ')
        label.extract()                          # 첫 문단에서 발언자 표시를 떼어 낸다(직위는 별도 열)
        paras = [t for t in (norm(c.get_text(' ')) for c in div.find_all(['p', 'table'], recursive=False)) if t]
        section = div.find_parent('div', class_=re.compile(r'^agnd_\d+$'))
        anchor = None
        if section is not None:
            n = section['class'][0].split('_')[1]
            anchor = f'agnd_{n}' if f'agnd_{n}' in anchors else None
        turns.append({'no': no, 'position': position, 'name': name, 'paras': paras, 'anchor': anchor,
                      'label_hit': bool(HIT.search(label_text))})
    in_turns = sum(len(HIT.findall(' '.join(t['paras']))) + len(HIT.findall(t['position'] + t['name'])) for t in turns)
    outside = total - in_turns                  # 의사일정·참석자표·표지 등 발언이 아닌 곳의 언급
    return title, turns, outside


def excerpt(paras):
    """언급 문단 +-1문단을 합친다. 맞닿거나 겹치는 구간은 하나로, 떨어진 구간은 [중략]으로 잇는다. (본문, 언급 문단 수)"""
    hits = [i for i, p in enumerate(paras) if HIT.search(p)]
    if not hits:
        return '', 0
    blocks = []
    for i in hits:
        lo, hi = max(0, i - 1), min(len(paras) - 1, i + 1)
        if blocks and lo <= blocks[-1][1] + 1:
            blocks[-1][1] = max(blocks[-1][1], hi)
        else:
            blocks.append([lo, hi])
    return '\n[중략]\n'.join('\n'.join(paras[lo:hi + 1]) for lo, hi in blocks), len(hits)


def read_manifest():
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(encoding='utf-8-sig', newline='') as f:
        return {r['file']: r for r in csv.DictReader(f)}


def meeting_type(name):
    body = re.sub(r'^\[임시회의록\]\s*제\d+회\s+제\d+[차일]\s+|^제\d+회\s+제\d+[차일]\s+', '', name)
    if '행정사무감사' in body:
        return '행정사무감사'
    if '행정사무조사' in body:
        return '행정사무조사'
    if body.startswith('본회의'):
        return '본회의'
    if '예산결산' in body:
        return '예산결산특별위원회'
    if '특별위원회' in body:
        return '기타 특별위원회'
    return '상임위원회' if '위원회' in body else '기타'


def build_rows(raw_dir, manifest):
    """원문 폴더 전체 -> (CSV 행, 통계). 같은 회의에 확정본과 임시본이 함께 있으면 확정본만 쓴다."""
    files = sorted(raw_dir.glob('*.html'))
    meeting = lambda f: f.name.rsplit('_mnts', 1)[0]           # 파일명 앞부분 = 날짜+회의명
    final_meetings = {meeting(f) for f in files if not f.stem.endswith('_임시')}
    rows, st = [], {'원문_수': 0, '발언없는_회의_수': 0, '본문밖_언급_회의_수': 0, '직함_언급_발언_수': 0,
                    '언급문단_수': 0, '검색어별_언급횟수': Counter()}
    docs_with_rows = []
    for f in files:
        m = re.search(r'_mnts(\d+)(_임시)?\.html$', f.name)
        mnts_id, provisional = m.group(1), bool(m.group(2))
        if provisional and meeting(f) in final_meetings:
            continue
        st['원문_수'] += 1
        title, turns, outside = parse_minutes(f.read_text(encoding='utf-8'))
        date, session, name = split_title(title, provisional)
        fetched = (manifest.get(f.name) or {}).get('fetched_at') or datetime.fromtimestamp(f.stat().st_mtime, KST).isoformat(timespec='seconds')
        st['본문밖_언급_회의_수'] += outside > 0
        n_rows = 0
        for t in turns:
            text, n_hit = excerpt(t['paras'])
            if not n_hit:
                st['직함_언급_발언_수'] += t['label_hit']
                continue
            n_rows += 1
            st['언급문단_수'] += n_hit
            st['검색어별_언급횟수'].update(term for p in t['paras'] for term in HIT.findall(p))
            url = f'{BASE}/cms/mntsViewer.do?mntsId={mnts_id}' + (f"#{t['anchor']}" if t['anchor'] else '')
            rows.append({'doc_id': f"CWC-{mnts_id}-{t['no']:04d}", '회의일': date, '회의명': name, '회차': session,
                         '발언자 직위': t['position'], '발언 원문': text, '출처 URL': url, '수집시각': fetched})
        if n_rows:
            docs_with_rows.append((date, name))
        else:
            st['발언없는_회의_수'] += 1
    rows.sort(key=lambda r: (r['회의일'], int(r['doc_id'].split('-')[1]), r['doc_id']))   # 날짜 -> 회의 ID(숫자) -> 발언 순서
    st['발언_수'] = len(rows)
    st['발언있는_회의_수'] = len(docs_with_rows)
    st['연도별_발언'] = dict(sorted(Counter(r['회의일'][:4] for r in rows).items()))
    st['연도별_회의'] = dict(sorted(Counter(d[:4] for d, _ in docs_with_rows).items()))
    st['유형별_발언'] = dict(Counter(meeting_type(r['회의명']) for r in rows))
    st['유형별_회의'] = dict(Counter(meeting_type(n) for _, n in docs_with_rows))
    st['연도x유형_발언'] = {y: dict(Counter(meeting_type(r['회의명']) for r in rows if r['회의일'][:4] == y)) for y in st['연도별_발언']}
    st['검색어별_언급횟수'] = dict(st['검색어별_언급횟수'])
    return rows, st


def write_csv(rows, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.tmp')
    with tmp.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, out)


def selftest():
    """네트워크 없이 파서·발췌 규칙을 점검한다(깨지면 AssertionError)."""
    page = """<html><div id="minutesTop"><h3>제149회 제2차 본회의(2026.01.26 월요일)</h3></div>
    <div id="minutesContentArea"><div class='agnd_h'><p>출석 누비자운영팀장 견종일</p></div>
    <div class='agnd_1'><p><a name='agnd_1'></a><span class='bld'>1. 공영자전거 조례안</span></p>
    <div class='SPKRMBR1'><p><span class='spkrbld'>○<span class='MBR1'>김의원</span>  의원</span>  첫 문단입니다.</p>
    <p class='spc1'>누비자가 좋습니다.</p><p class='spc1'>다음 문단.</p><p class='spc1'>무관 1.</p><p class='spc1'>무관 2.</p>
    <p class='spc1'>공영자전거 말씀.</p><p class='spc1'>끝.</p></div>
    <div class='SPKR9'><p><span class='spkrbld'>○창원레포츠파크 누비자운영팀장 견종일</span>  답변드립니다.</p></div>
    <div class='SPKR8'><p><span class='spkrbld'>○시장 홍길동</span>  네.</p><p class='spc1'>공영자전거 확대.</p></div></div></div></html>"""
    title, turns, outside = parse_minutes(page)
    assert split_title(title, False) == ('2026-01-26', '제149회 제2차', '제149회 제2차 본회의')
    assert [(t['position'], t['name']) for t in turns] == [('의원', '김의원'), ('창원레포츠파크 누비자운영팀장', '견종일'), ('시장', '홍길동')]
    mk = lambda t: split_label(BeautifulSoup(f"<span class='spkrbld'>{t}</span>", 'html.parser').span)
    assert mk('○창원경륜공단 공영자전거팀장') == ('창원경륜공단 공영자전거팀장', '')      # 이름 없는 표시
    assert mk('○창원레포츠파크이사장직무대행 홍명표') == ('창원레포츠파크이사장직무대행', '홍명표')
    assert mk('○창원레포츠파크 이사장') == ('창원레포츠파크 이사장', '') and mk('○위원장 박선애') == ('위원장', '박선애')
    assert outside == 2, outside                       # 참석자 1 + 의사일정 제목 1
    text, n = excerpt(turns[0]['paras'])               # 첫문단 제거 후: [첫,누비자,다음,무관1,무관2,공영,끝]
    assert n == 2 and text == '첫 문단입니다.\n누비자가 좋습니다.\n다음 문단.\n[중략]\n무관 2.\n공영자전거 말씀.\n끝.', text
    assert excerpt(turns[1]['paras']) == ('', 0) and turns[1]['label_hit']   # 직함에만 있는 언급은 제외
    assert excerpt(turns[2]['paras'])[0] == '네.\n공영자전거 확대.' and turns[2]['anchor'] == 'agnd_1'
    assert meeting_type('제148회 제3차 예산결산특별위원회') == '예산결산특별위원회'
    assert meeting_type('[임시회의록] 제155회 제1일 건설해양농림위원회행정사무감사') == '행정사무감사'
    assert meeting_type('제149회 제2차 본회의') == '본회의' and meeting_type('제148회 제7차 기획행정위원회') == '상임위원회'
    with tempfile.TemporaryDirectory() as d:           # 같은 회의의 임시본·확정본이 함께 있으면 확정본만 쓴다
        for name in ('20260126_제149회_제2차_본회의_mnts1_임시.html', '20260126_제149회_제2차_본회의_mnts2.html'):
            (Path(d) / name).write_text(page, encoding='utf-8')
        rows, st = build_rows(Path(d), {})
        assert st['원문_수'] == 1 and rows and all(r['doc_id'].startswith('CWC-2-') for r in rows)
        assert [r['발언자 직위'] for r in rows] == ['의원', '시장']      # 직함에만 언급된 발언은 행이 없다
    with tempfile.TemporaryDirectory() as d:           # 덮어쓰기 금지: 같은 이름의 원문이 있으면 건너뛰는지
        global RAW, MANIFEST
        old = RAW, MANIFEST
        RAW, MANIFEST = Path(d), Path(d) / '_manifest.csv'
        try:
            h = {'mnts_id': '1', 'title': '제1회 제1차 본회의(2026.01.01 목요일)', 'date': '2026-01-01', 'provisional': False, 'terms': {'누비자'}}
            (RAW / raw_name(h)).write_bytes(b'x')
            assert save_new(None, h) is None and (RAW / raw_name(h)).read_bytes() == b'x'
        finally:
            RAW, MANIFEST = old
    print('selftest ok')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--parse-only', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    if args.selftest:
        selftest()
        return 0
    failed = []
    if not args.parse_only:
        client = Client()
        docs, summary = collect_hits(client)
        new = 0
        for i, h in enumerate(sorted(docs.values(), key=lambda h: h['date']), 1):
            try:
                if save_new(client, h):
                    new += 1
                    print(f"[저장 {i}/{len(docs)}] {h['date']} {h['title']}", flush=True)
            except (RuntimeError, ValueError, requests.RequestException) as e:   # 한 건 실패로 전체를 멈추지 않고 모아서 알린다
                failed.append({'mnts_id': h['mnts_id'], 'title': h['title'], 'error': str(e)})
                print(f"[실패 {i}/{len(docs)}] {h['title']}: {e}", flush=True)
        print(json.dumps({'검색요약': summary, '대상_회의_수': len(docs), '새로_저장': new, '실패': failed}, ensure_ascii=False, indent=1))
    rows, stats = build_rows(RAW, read_manifest())
    write_csv(rows, OUT)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 1 if failed else 0       # 실패가 있으면 다시 실행하면 빠진 회의만 이어서 받는다


if __name__ == '__main__':
    sys.exit(main())
