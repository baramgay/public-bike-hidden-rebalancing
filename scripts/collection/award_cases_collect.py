"""공식 수상사례 PDF 수집. 실패는 비정상 종료하며 기존 원본을 덮어쓰지 않는다."""
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

ITEMS = [('statistics2022_kim_policy_effect.pdf', 'https://mods.go.kr/boardDownload.es?bid=11911&list_no=421220&seq=1'), ('statistics2023_report_103836.pdf', 'https://data.mods.go.kr/eduhome/bbs/BbsFileDownload.do?atchFileId=FILE_000000000103836&fileSn=0'), ('statistics2023_report_103835.pdf', 'https://data.mods.go.kr/eduhome/bbs/BbsFileDownload.do?atchFileId=FILE_000000000103835&fileSn=0'), ('suwon2025_data_contest_brief.pdf', 'https://www.suwon.re.kr/data/file/brief/9a18cb18b51051343b55f6e23616a830_TMFKY93J_65678966531ed3446d4ff9e228630481fcf4ad9b.pdf'), ('molit2025_awards_official_list.pdf', 'https://itskorea.kr/downloadFile.do?fileId=FILE_000000000104966&fileSn=0')]


def main():
    results = []
    failed = False
    for name,url in ITEMS:
        try:
            results.append(download(url,ROOT/'data/raw/award_cases'/name,'pdf'))
        except Exception as error:
            failed = True
            results.append({'file':name,'state':'failed','error':str(error)})
    metadata = ROOT/'data/metadata/award_cases_downloads_latest.json'
    metadata.parent.mkdir(parents=True,exist_ok=True)
    temporary = metadata.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(metadata)
    print(json.dumps(results,ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
