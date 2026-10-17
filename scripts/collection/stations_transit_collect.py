"""공개 자료 수집. 기존 파일은 형식 확인 후 건너뛰고 부분파일은 보존한다."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[2]


def validate_file(path, kind):
    if path.stat().st_size == 0:
        raise ValueError(f"빈 파일: {path.name}")
    with path.open('rb') as stream:
        head = stream.read(8192)
    lower = head.lstrip(b'\xef\xbb\xbf \r\n\t').lower()
    if kind == 'csv':
        if lower.startswith((b'<html', b'<!doctype', b'<script')) or b',' not in head.splitlines()[0]:
            raise ValueError(f"CSV 형식 불일치: {path.name}")
        for encoding in ('utf-8-sig', 'cp949'):
            try:
                head.splitlines()[0].decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"CSV 헤더 인코딩 오류: {path.name}")
    elif kind == 'xlsx':
        with zipfile.ZipFile(path) as archive:
            if '[Content_Types].xml' not in archive.namelist() or 'xl/workbook.xml' not in archive.namelist() or archive.testzip() is not None:
                raise ValueError(f"XLSX 형식 불일치: {path.name}")
    elif kind == 'pdf':
        if not head.startswith(b'%PDF-'):
            raise ValueError(f"PDF 형식 불일치: {path.name}")
    elif kind == 'html':
        if b'<html' not in lower and b'<!doctype' not in lower:
            raise ValueError(f"HTML 형식 불일치: {path.name}")
    else:
        raise ValueError(f"지원하지 않는 형식: {kind}")


def download(url, target, kind, expected_bytes=None):
    started_utc = datetime.now(timezone.utc).isoformat()
    target = Path(target)
    if target.exists():
        validate_file(target, kind)
        if expected_bytes is not None and target.stat().st_size != expected_bytes:
            raise ValueError(f"기존 파일 길이 불일치: {target.name}")
        return {'file': target.name, 'state': 'skipped_existing', 'bytes': target.stat().st_size}
    partial = target.with_name(target.name + '.partial')
    if partial.exists():
        raise FileExistsError(f"부분파일 보존 중, 자동 재시도 금지: {partial.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    received = 0
    with requests.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        length = int(response.headers['Content-Length'])
        with partial.open('xb') as stream:
            for chunk in response.iter_content(65536):
                stream.write(chunk)
                digest.update(chunk)
                received += len(chunk)
    if received != length or (expected_bytes is not None and received != expected_bytes):
        raise ValueError(f"수신 길이 불일치: {target.name}: {received}/{length}")
    validate_file(partial, kind)
    if target.exists():
        raise FileExistsError(f"수집 중 최종파일 생성됨, 덮어쓰기 금지: {target.name}")
    os.replace(partial, target)
    return {'file': target.name, 'state': 'complete', 'bytes': received, 'sha256': digest.hexdigest(), 'url': url, 'started_utc': started_utc, 'finished_utc': datetime.now(timezone.utc).isoformat()}

import re


def main():
    raw = ROOT / 'data/raw'
    failed = False
    jobs = [
        ('https://www.data.go.kr/data/15000545/fileData.do', raw/'nubija_stations/data_go_kr_15000545.html', 'html'),
        ('https://www.lepopark.or.kr/contents/manage/manage04', raw/'operations/lepopark_manage04.html', 'html'),
        ('https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003645686&fileDetailSn=1&insertDataPrcus=N', raw/'nubija_stations/nubija_stations_2023_2025.xlsx', 'xlsx'),
    ]
    for dataset, folder, label in [('15037805','transit','bus_stops'),('15152427','transit','bus_timetable'),('15127335','transit','bus_routes_fleet'),('3066436','spatial','registered_factories')]:
        page = raw/f'{folder}/data_go_kr_{dataset}.html'
        try:
            print(json.dumps(download(f'https://www.data.go.kr/data/{dataset}/fileData.do',page,'html'),ensure_ascii=False))
            urls = re.findall(r'"contentUrl"\s*:\s*"([^"\r\n]+)"',page.read_text(encoding='utf-8'))
            if not urls:
                raise ValueError(f'공식 다운로드 URL 없음: {dataset}')
            for number,url in enumerate(urls):
                # These four preserved catalogue attachments are CSV data.
                jobs.append((url,raw/f'{folder}/{label}_{dataset}_{number}.csv','csv'))
        except Exception as error:
            failed = True
            print(json.dumps({'dataset':dataset,'state':'failed','error':str(error)},ensure_ascii=False))
    for dataset in ['15098529','15098530','15098534','15000386']:
        jobs.append((f'https://www.data.go.kr/data/{dataset}/openapi.do',raw/f'transit/api_documentation_{dataset}.html','html'))
    for url,target,kind in jobs:
        try:
            print(json.dumps(download(url,target,kind),ensure_ascii=False))
        except Exception as error:
            failed = True
            print(json.dumps({'file':target.name,'state':'failed','error':str(error)},ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
