# 승인된 ASOS 일자료·TAGO 수집기

준비일: 2026-10-16. ASOS 일자료(15059093)와 TAGO 노선·정류소·도착정보의 사용자 계정 개발 승인이 확인된 범위만 호출한다. ASOS 시간자료15057210은 미신청이므로 호출하지 않는다. 이 준비 단계에서는 실제 API 호출을 하지 않았다.

## 실행 전

사용자가 프로젝트 루트 `.env.local`에 `DATA_GO_KR_SERVICE_KEY`를 로컬 저장한다. 기존 카카오 키와 다른 변수를 덮어쓰지 않는다. 키를 채팅·문서·스크린샷·Git에 넣지 않는다. 스크립트는 이 변수만 읽으며 키가 없으면 네트워크 요청 없이 종료코드2로 끝난다. `.env.local`은 스크립트 위치에서 찾으므로 현재 작업 디렉터리에 의존하지 않는다.

일반 인증키의 Decoding 또는 Encoding 표기를 모두 처리한다. 퍼센트 인코딩은 `urllib.parse.unquote`로 한 번 해제한 뒤 요청 라이브러리가 한 번 인코딩한다. `unquote_plus`를 쓰지 않아 원래 키의 `+`를 공백으로 바꾸지 않는다. 인증 URL과 예외 원문은 출력하지 않는다. 환경변수·다른 파일에서 키를 임의 탐색하지 않는다.

## 실행 명령

프로젝트 루트에서:

    python scripts/collection/collect_approved_public_apis.py

ASOS 일자료 또는 TAGO만 별도 실행:

    python scripts/collection/collect_approved_public_apis.py --only asos
    python scripts/collection/collect_approved_public_apis.py --only tago

도착정보는 기본 실행에서 호출하지 않는다. 꼭 필요하면 수집된 창원 정류소의 nodeid 하나만 지정한다:

    python scripts/collection/collect_approved_public_apis.py --only tago --arrival-node-id CHANGWON_NODE_ID

`CHANGWON_NODE_ID`는 예시 자리표시자다. 실제 수집된 ID로 바꿔야 하며 임의 추정 ID는 쓰지 않는다. 도착정보는 그 정류소의 현재 표본1회이며 도시 전체·주기적 폴링이 아니다. 같은 명령을 반복하면 현재 데이터가 새로 조회되므로 필요할 때만 실행한다.

## 공식 명세와 요청

| 구분 | 공식 문서 | 요청 경로·핵심 파라미터 |
|---|---|---|
| ASOS 일 | https://www.data.go.kr/data/15059093/openapi.do | `/1360000/AsosDalyInfoService/getWthrDataList`: `dataType=JSON`, `dataCd=ASOS`, `dateCd=DAY`, `stnIds=155`, 연도별 `startDt/endDt`, `pageNo/numOfRows` |
| TAGO 노선 | https://www.data.go.kr/data/15098529/openapi.do | `/1613000/BusRouteInfoInqireService/getCtyCodeList`, `getRouteNoList`, `getRouteAcctoThrghSttnList`; `_type=json`, `cityCode`, 경유정류소는 `routeId` |
| TAGO 정류소 | https://www.data.go.kr/data/15098534/openapi.do | `/1613000/BusSttnInfoInqireService/getSttnNoList`: `_type=json`, `cityCode`, `pageNo/numOfRows` |
| TAGO 도착 | https://www.data.go.kr/data/15098530/openapi.do | `/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList`: `_type=json`, `cityCode`, `nodeId`, `pageNo/numOfRows` |

호스트는 `https://apis.data.go.kr`이다. 인증값은 요청에만 포함하고 저장하지 않는다. ASOS와 TAGO의 JSON 파라미터가 다르므로 혼용하지 않는다. 공식 페이지와 계정 승인 오퍼레이션을 대조했다. 인증 후 실제 응답은 아직 확인하지 않았으며, 서비스 동작을 검증 완료한 것으로 표현하지 않는다.

## 수집 순서·범위

1. ASOS155 일자료를2023·2024·2025년 각각 조회한다. 예상일수는365·366·365, 합1,096일이다. 달력의 모든 날짜, 날짜중복, 지점155를 검사한다. 실제 누락이 있으면 보간하지 않고 실패 상태와 누락일을 기록한다.
2. TAGO 노선 서비스의 도시코드 목록에서 이름이 ‘창원’ 또는 ‘창원시’인 항목 하나를 선택한다. 코드를 하드코딩하지 않는다. 도시가 없거나 둘 이상이면 중단한다.
3. 창원의 정류소 목록과 노선 목록 전체 페이지를 받는다. 각 노선의 routeid로 경유 정류소 전체 페이지를 받고 합친 파생 CSV도 만든다.
4. 선택한 경우만 현재 도착예정 표본을 받는다. 정류소가 방금 받은 창원 목록에 없으면 호출하지 않는다.

ASOS 주요 요소는 `avgTa`, `minTa`, `maxTa`(°C), `sumRn`(mm), `avgWs`·`maxWs`(m/s), `avgRhm`(%) 등이다. 모든 원문 필드를 보존하고 빈 강수량을0으로 바꾸지 않는다. 일자료는 시간대별 날씨가 아니며 일별 집계 기준도 공식 설명을 확인한다. 창원155가 도시 전체 국지기상을 대표한다고 가정하지 않는다. AWS는 승인·명세가 확인되지 않아 이 스크립트에 없다.

TAGO 필드는 실제 반환되는 `nodeid`, `nodenm`, `gpslati`, `gpslong`, `routeid`, `routeno`, `nodeord` 등을 원형으로 보존한다. 현재 노선망을 과거2023~2025의 운행망으로 소급하지 않는다. 경유목록은 정류소별 전수 시간표가 아니다. 도착예정시간은 과거 실적이나 실제 환승 자료가 아니다.

## 페이지·오류·쿼터

- 페이지 크기100, 페이지번호1부터 순차 요청한다. totalCount의 일관성, 응답 pageNo(제공될 때), 각 페이지 예상행수, 반복 페이지, 최종 누적행수를 검사한다. 도시목록처럼 비페이지형 응답은 한 번만 요청한다.
- HTTP200 외에 기관 `response.header.resultCode`가00 또는0인지 검사한다. JSON 대신 XML 오류가 오면 `.non_json.txt`로 원형 보존하고 중단한다. 인증값이 응답에 반사되면 해당 본문을 저장하지 않는다.
- 자동 재시도 없음, 요청 사이 최소0.3초. 계정에서 확인된 기능별 일10,000회보다 낮게 각 실행·기능별1,000회 상한을 둔다. 다른 프로그램의 당일 사용량을 조회한 것은 아니며 기관의 할당량 오류가 나오면 즉시 중단한다. 상한 변경·증설·추가 신청은 하지 않는다.
- 실패 원문 예외에는 인증 URL이 섞일 수 있어 출력하지 않는다. 정제된 상태·오류코드, 실패 오퍼레이션, 키 없는 endpoint와 공식 문서 링크를 실행 메타데이터에 남긴다. 일부 받은 응답은 보존하며 부분 수집을 완료라고 표시하지 않는다.

## 산출물

매 실행마다 고유 UTC 폴더를 만들며 기존 원본을 덮어쓰지 않는다.

- 원형 응답: `data/raw/approved_public_apis/<실행UTC>/<오퍼레이션>/*.json`
- 파생 CSV: 같은 실행 폴더의 `derived_csv/`. 원문값을 유지하며 형변환·보간·지오코딩·모델링은 하지 않는다.
- 상세 검증·무결성: `data/metadata/approved_public_apis/<실행UTC>/run.json`
- 읽기용 상태: 같은 폴더 `run.md`

메타데이터에는 출처, 키를 뺀 요청조건, 수집시각UTC, 페이지·행수, 실제 필드, 필드별 빈값·결측, ASOS 실제 날짜범위·누락일, 원형·파생파일의 크기·SHA256, 호출수와 실패상태를 남긴다. ASOS는 공공누리제1유형(출처표시), TAGO는 포털 이용허락범위 제한 없음이다. 실제 재배포 전 최신 조건도 확인한다.

## 로컬 검증 결과와 한계

    python scripts/collection/test_approved_public_apis.py

Python3.14.5 표준라이브러리만 사용하며 외부패키지를 설치하지 않았다. 키인코딩, 누락키의 무호출 종료, HTTP200의 기관오류 검출, 단일/빈응답 정규화, 페이지번호 불일치, 연간 날짜누락·중복 검사를 포함한7개 로컬 테스트를 실행해 통과했다. `--help` 실행도 성공했다. 실제 인증호출·기관 응답·전체수집은 키 저장 후 별도로 확인해야 한다. 로컬 테스트 성공은 실제 수집 성공이 아니다.
