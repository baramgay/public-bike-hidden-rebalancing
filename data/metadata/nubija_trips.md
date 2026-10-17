# 누비자 대여·반납 원자료 수집 및 검증

## 수집·검증 상태 요약

| 대상 | 완전 수신 | 전체 CSV 검증 | 레코드 수 | 출발기간 및 한계 |
|---|---|---|---:|---|
| 2025 CSV | 237,421,293 bytes | 완료, CP949, 7컬럼 빈값 0 | 4,419,063 | 2025-01-01~12-31. 7월 31일 전체 누락, 11개 출발월만 존재 |
| 2024 CSV | 245,633,968 bytes | 완료, CP949, 7컬럼 빈값 0 | 4,582,332 | 2024-01-01~12-31. 12개 출발월 존재 |
| 2023 CSV | 216,640,346 bytes | 완료, CP949, 7컬럼 빈값 0 | 4,066,540 | 2023-01-01~12-31. 12개 출발월 존재 |
| 2022로 등록된 ZIP | 미완료(기대 159,003,222 bytes) | 미검증 | 미확정 | 공식 원본 파일명은 20~22 터미널 대여반납정보.zip. 첫 로컬 헤더의 2020-01 CSV만 관찰, 전체 목차·범위 미확정 |

완료된 3개 CSV는 원본을 변경하지 않았다. 2025년 7월은 실제 수요 0으로 해석하거나 보간하면 안 된다. 원인 확인 전에는 해당 기간을 학습·평가에서 제외할 필요가 있다. 2023·2024의 12개 월 존재는 월 내부 모든 날짜·이벤트의 완전성까지 보장하지 않는다.

2025년 추가 검증에서 완전중복 0, 유효하지 않은 날짜시간 0, 음수대여시간/날짜역전 0, 0초 대여 506건을 확인했다. 24시간 초과 대여 3,195건(7일 이하 3,019, 7일 초과~30일 이하 126, 30일 초과 50)이 있다. 최대 대여시간은 15,667,437초다. 원본에 기록된 장기대여의 원인은 미확정이다.

2025년 터미널 참조 495개 코드와 미일치한 것은 출발329 1건, 도착7 107건·329 1건이다. 코드0/비숫자/명시적 미상 표시는 없었다. 2025년 심화 검증만 수행했으며 2023·2024는 기본 전체 검증 범위다.

2022 ZIP의 두 차례 전송은 각각 read timeout, 서버 IncompleteRead로 실패했다. 부분파일을 .partial로 보존하고 부모에게 공식 직접 URL을 전달했다. 정상 ZIP 확보 전에는 2022 자료가 확보되었다고 주장하면 안 된다.


공식 제공 페이지: https://www.data.go.kr/data/15126280/fileData.do

제공기관: 경상남도 창원시(환경정책과). 이용조건: 무료, 이용허락범위 제한 없음. 파일데이터는 로그인 없이 다운로드 가능. 로그인·활용신청·결제 없이 공식 첨부 다운로드 URL로 수집하였다. 원본 바이트를 변경하거나 다운로드 파일을 실행하지 않았다.

과거 자료 접근 경로: 제공 페이지 → 주기성 과거 데이터 → 해당 연도 → 데이터 다운로드 → CSV(2022년은 ZIP). 포털이 사용하는 공개 HTML 조회 경로 /tcs/dss/selectHistAndCsvData.do 와 /tcs/dss/selectDpkDetailInfo.do 에서 실제 첨부 ID를 확인하였다.

검증은 CSV 순차 읽기로 수행하며 원자료 전체를 메모리에 적재하지 않는다. 결측은 빈 문자열 또는 공백만 있는 셀로 정의한다. 날짜 범위는 원문 날짜 문자열의 최소·최대이며 비정상값을 임의 보정하지 않는다.

## 첫 다운로드 중단

2022~2025년 4개를 병렬 다운로드하였으나 모두 requests ConnectionError(ReadTimeoutError)로 중단되었다. 미완료 파일은 .partial 접미사를 붙였으며 분석에 사용하면 안 된다. Range 이어받기 요청을 서버가 206 대신 200 전체 파일로 응답하므로 재개할 수 없다. 2025년 단독 전체 재시도를 진행한다.

[("2022_'20~22 터미널 대여반납정보.zip.partial", 36700160), ('2023_창원레포츠파크_창원시무인대여공영자전거 2023년 누비자 대여반납 정보.csv.partial', 59768832), ('2024_창원레포츠파크_창원시무인대여공영자전거 2024년 누비자 대여반납 정보.csv.partial', 38797312), ('2025_창원레포츠파크_창원시무인대여공영자전거 2025년 누비자 대여반납 정보.csv.partial', 41943040)]

## 연도별 공식 첨부 및 미완료 파일 점검

아래는 첫 시도의 부분파일이다. SHA256은 수신된 부분 바이트에 대한 값이며 정상 원본의 해시가 아니다. 전체 레코드 수·전체 기간·전체 결측은 미검증이다.

### 2025년

- 부분파일: C:\업무\교통공모전\data\raw\nubija_trips\2025_창원레포츠파크_창원시무인대여공영자전거 2025년 누비자 대여반납 정보.csv.partial
- 부분 크기: 41943040 bytes
- 부분 SHA256: 08cecd87a31e9c6de4c2208857fc9405c3ec1aece52a90a535ccac5b415152fb
- 다운로드 URL: https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003638975&fileDetailSn=1&insertDataPrcus=N
- 과거 상세 팝업 URL: https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi:e7945cec-4ad8-4eb2-add8-ce6ca6727738&publicDataHistSn=1
- 선두 4 KB 엄격 디코딩 인코딩: cp949
- 선두 헤더 및 샘플: [["자전거번호", "출발터미널", "출발일", "출발시간", "도착터미널", "도착일", "도착시간"], ["7680", "96", "2025-01-01", "00:00:10", "93", "2025-01-01", "00:04:45"], ["10580", "265", "2025-01-01", "00:00:31", "265", "2025-01-01", "00:01:40"]]

### 2024년

- 부분파일: C:\업무\교통공모전\data\raw\nubija_trips\2024_창원레포츠파크_창원시무인대여공영자전거 2024년 누비자 대여반납 정보.csv.partial
- 부분 크기: 38797312 bytes
- 부분 SHA256: 5b6d7bff4460c655c6bd85bb30db4e009ddb8bad7c59d2cb210fe1d6bf0eaa28
- 다운로드 URL: https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003634157&fileDetailSn=1&insertDataPrcus=N
- 과거 상세 팝업 URL: https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi:3ad3b8d0-dc7c-4634-94a9-85f0b5f27d45&publicDataHistSn=1
- 선두 4 KB 엄격 디코딩 인코딩: cp949
- 선두 헤더 및 샘플: [["자전거번호", "출발터미널", "출발일", "출발시간", "도착터미널", "도착일", "도착시간"], ["8114", "101", "2024-01-01", "00:00:18", "277", "2024-01-01", "03:17:20"], ["9125", "81", "2024-01-01", "00:00:44", "106", "2024-01-01", "00:53:20"]]

### 2023년

- 부분파일: C:\업무\교통공모전\data\raw\nubija_trips\2023_창원레포츠파크_창원시무인대여공영자전거 2023년 누비자 대여반납 정보.csv.partial
- 부분 크기: 59768832 bytes
- 부분 SHA256: a3b2cfa43e50fd556f960146f65cb972fd931f8e37de6f487c4670a78a6db2d5
- 다운로드 URL: https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003630519&fileDetailSn=1&insertDataPrcus=N
- 과거 상세 팝업 URL: https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi:6df2e0b4-f0b9-4c20-be24-fd1846338ce7&publicDataHistSn=2
- 선두 4 KB 엄격 디코딩 인코딩: cp949
- 선두 헤더 및 샘플: [["자전거번호", "출발터미널", "출발일", "출발시간", "도착터미널", "도착일", "도착시간"], ["6254", "42", "2023-01-01", "00:00:25", "42", "2023-01-01", "00:00:52"], ["9660", "284", "2023-01-01", "00:01:13", "201", "2023-01-01", "00:08:49"]]

### 2022년

- 부분파일: C:\업무\교통공모전\data\raw\nubija_trips\2022_'20~22 터미널 대여반납정보.zip.partial
- 부분 크기: 36700160 bytes
- 부분 SHA256: eb37c4353f798db2d7cf7ea329f3116b0434d6e18d4157e5abec54294d1c4bb5
- 다운로드 URL: https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002865115&fileDetailSn=1&insertDataPrcus=N
- 과거 상세 팝업 URL: https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi:7a491576-7b50-4eb0-8f2c-c549f00fd96e&publicDataHistSn=1
- ZIP 부분파일이므로 완전한 ZIP 목차·CRC·내부 파일 검증 불가.

시각 UTC: 2026-10-16T14:19:44.147434+00:00

## 원본 크기 HEAD 확인

[
  {
    "year": 2022,
    "status": 200,
    "content_length": "159003222",
    "content_type": "application/octet-stream; charset=UTF-8",
    "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002865115&fileDetailSn=1&insertDataPrcus=N",
    "checked_utc": "2026-10-16T14:20:10.979861+00:00"
  },
  {
    "year": 2023,
    "status": 200,
    "content_length": "216640346",
    "content_type": "application/octet-stream; charset=UTF-8",
    "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003630519&fileDetailSn=1&insertDataPrcus=N",
    "checked_utc": "2026-10-16T14:20:11.644875+00:00"
  },
  {
    "year": 2024,
    "status": 200,
    "content_length": "245633968",
    "content_type": "application/octet-stream; charset=UTF-8",
    "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003634157&fileDetailSn=1&insertDataPrcus=N",
    "checked_utc": "2026-10-16T14:20:12.260557+00:00"
  }
]

## 실행 환경 및 재현 스크립트

- Python: 3.14.5 (tags/v3.14.5:5607950, May 10 2026, 10:43:50) [MSC v.1944 64 bit (AMD64)]
- requests: 2.34.2
- pandas: 2.3.3
- 실행 방식: PowerShell here-string을 python - 표준입력으로 실행하였다. 실행 중 코드를 아래 .py 파일로 동일 기능 복사 보존하였다. 스크립트를 다시 실행한 것은 아니다.
- 2025 단독 재시도: scripts/collection/nubija_trips_collect_2025.py
- 2024→2023→2022 순차 대기열: scripts/collection/nubija_trips_collect.py
- 스트리밍 원본 검증: scripts/collection/nubija_trips_validate.py
- 재현 명령: python scripts/collection/nubija_trips_collect_2025.py (먼저), python scripts/collection/nubija_trips_collect.py (다음), python scripts/collection/nubija_trips_validate.py (검증). 프로젝트 루트에서 실행한다. 현재 수집과 동시에 재실행하면 안 된다. 기존 .partial은 xb 모드로 덮어쓰지 않는다.
- 완료조건: HTTP 성공, 실제 수신 bytes == HTTP Content-Length, 수신 중 계산한 SHA256 기록. 그 뒤 .partial을 최종 확장자로 변경한다. 전체 CSV의 엄격 디코딩·파싱 성공과 행수·결측·기간은 별도 검증 프로세스가 기록한다.
- 재시도 규칙: 첫 4개 병렬시도 read timeout 뒤 .partial 보존. Range 요청이 무시됨(200 응답)을 확인하고 부분 덧붙이기 금지. 2025 단독 1회(20/180초 connect/read timeout), 이후 연도별 단독 1회(30/300초), 64 KiB chunk. 자동 반복 재시도 없음.
- SHA256은 무결성 확인용 로컬 fingerprint이며 제공기관 공인 체크섬과 대조한 값은 아니다. HTTP 전체 길이 일치가 데이터의 의미적 완전성을 보장하지 않는다.
- 검증 한계: CSV 빈 문자열·공백 결측을 집계한다. 날짜는 원문 문자열 min/max; 유효한 datetime, 중복·시간 역전·극단 이용시간은 이 수집 검증에서 미검사다.

## 2025년 단독 재시도 완료

{
  "path": "C:\\업무\\교통공모전\\data\\raw\\nubija_trips\\nubija_trips_2025.csv",
  "bytes": 237421293,
  "sha256": "e4b269df2bf018095f358eb56067464c6554fb41713ad1cd9a5765affb3606dc",
  "started_utc": "2026-10-16T14:19:03.447491+00:00",
  "finished_utc": "2026-10-16T14:23:50.204507+00:00",
  "url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003638975&fileDetailSn=1&insertDataPrcus=N"
}

### 전체 CSV 검증: nubija_trips_2025.csv

```json
{
  "entry": "nubija_trips_2025.csv",
  "encoding": "cp949",
  "records": 4419063,
  "columns": [
    "자전거번호",
    "출발터미널",
    "출발일",
    "출발시간",
    "도착터미널",
    "도착일",
    "도착시간"
  ],
  "missing_blank_cells": {
    "자전거번호": 0,
    "출발터미널": 0,
    "출발일": 0,
    "출발시간": 0,
    "도착터미널": 0,
    "도착일": 0,
    "도착시간": 0
  },
  "date_ranges_raw_strings": {
    "출발일": [
      "2025-01-01",
      "2025-12-31"
    ],
    "도착일": [
      "2025-01-01",
      "2026-04-19"
    ]
  },
  "monthly_counts": {
    "출발일": {
      "2025-01": 285893,
      "2025-02": 263751,
      "2025-03": 354347,
      "2025-04": 426347,
      "2025-05": 455061,
      "2025-06": 468339,
      "2025-08": 410323,
      "2025-09": 482773,
      "2025-10": 449061,
      "2025-11": 444166,
      "2025-12": 379002
    },
    "도착일": {
      "2025-01": 285815,
      "2025-02": 263716,
      "2025-03": 354355,
      "2025-05": 454933,
      "2025-04": 426279,
      "2025-06": 468448,
      "2025-08": 410227,
      "2025-07": 191,
      "2025-09": 482683,
      "2025-10": 449051,
      "2025-11": 444222,
      "2026-01": 93,
      "2026-02": 5,
      "2025-12": 379037,
      "2026-04": 2,
      "2026-03": 6
    }
  },
  "unique_terminal_counts": {
    "출발터미널": 462,
    "도착터미널": 463
  },
  "first_3_records": [
    [
      "7680",
      "96",
      "2025-01-01",
      "00:00:10",
      "93",
      "2025-01-01",
      "00:04:45"
    ],
    [
      "10580",
      "265",
      "2025-01-01",
      "00:00:31",
      "265",
      "2025-01-01",
      "00:01:40"
    ],
    [
      "11587",
      "326",
      "2025-01-01",
      "00:00:52",
      "98",
      "2025-01-01",
      "00:24:39"
    ]
  ],
  "checked_utc": "2026-10-16T14:24:11.425595+00:00"
}
```

## 2025년 품질상 주의사항(전체 원본 기반)

- 출발일 월별 집계에서 2025-07가 전혀 없다(0행). 11개 출발월만 있다. 포털 설명의 1~12월과 달리 완전한 연간 기록으로 가정하면 안 된다. 원인(등록 누락, 추출 누락, 서비스 정지 등)은 확인되지 않았다.
- 도착일의 최대 원문값은 2026-04-19이다. 출발연도 밖 반납이 존재한다. 지연 반납·분실 처리·입력오류 여부는 원인 미확정이며 이용시간 계산 시 확인이 필요하다.
- 터미널 코드 종류는 출발 462/도착 463이다. 이를 현재 운영 터미널 개수로 해석하면 안 되며 연도별 코드·설치/폐쇄 이력과 대조해야 한다.

## 2025년 심화 품질 검증

원본은 변경하지 않았다. 월 누락을 보간하지 않았으며 원인 미확정이다. 관측이 없는 7월은 수요 0으로 처리하지 않고 모델 학습·성능평가에서 제외할 필요가 있다. 대여시간 구간은 상호 배타적(음수·0·각 양수 구간)이며 날짜역전은 별도 중첩 집계다.

```json
{
  "records": 4419063,
  "station_reference": "C:\\업무\\교통공모전\\data\\raw\\nubija_stations\\nubija_stations_2023_2025.xlsx",
  "station_sheet": "2025년",
  "station_rows": 495,
  "station_unique_codes": 495,
  "datetime_format": "%Y-%m-%d %H:%M:%S",
  "duration_seconds_min": 0.0,
  "duration_seconds_max": 15667437.0,
  "counts": {
    "invalid_start_datetime": 0,
    "invalid_end_datetime": 0,
    "negative_duration": 0,
    "zero_duration": 506,
    "positive_to_5min": 901369,
    "over_5_to_15min": 2028505,
    "over_15_to_30min": 806235,
    "over_30_to_60min": 393142,
    "over_1_to_2h": 225676,
    "over_2_to_24h": 60435,
    "over_24h_to_7d": 3019,
    "over_7d_to_30d": 126,
    "over_30d": 50,
    "end_calendar_date_before_start": 0
  },
  "missing_departure_dates": [
    "2025-07-01",
    "2025-07-02",
    "2025-07-03",
    "2025-07-04",
    "2025-07-05",
    "2025-07-06",
    "2025-07-07",
    "2025-07-08",
    "2025-07-09",
    "2025-07-10",
    "2025-07-11",
    "2025-07-12",
    "2025-07-13",
    "2025-07-14",
    "2025-07-15",
    "2025-07-16",
    "2025-07-17",
    "2025-07-18",
    "2025-07-19",
    "2025-07-20",
    "2025-07-21",
    "2025-07-22",
    "2025-07-23",
    "2025-07-24",
    "2025-07-25",
    "2025-07-26",
    "2025-07-27",
    "2025-07-28",
    "2025-07-29",
    "2025-07-30",
    "2025-07-31"
  ],
  "unknown_station_codes_and_counts": {
    "출발터미널": {
      "329": 1
    },
    "도착터미널": {
      "7": 107,
      "329": 1
    }
  },
  "special_or_nonnumeric_codes_and_counts": {
    "출발터미널": {},
    "도착터미널": {}
  },
  "duplicate_definition": "Exact equality of all seven parsed original text fields; SQLite full-key GROUP BY, no probabilistic hashes",
  "duplicate_groups": 0,
  "duplicate_excess_rows": 0,
  "rows_in_duplicate_groups": 0,
  "duplicate_examples": [],
  "anomaly_examples": {
    "over_30d": [
      [
        "7233",
        "478",
        "2025-01-15",
        "13:32:47",
        "243",
        "2025-02-17",
        "09:22:10"
      ],
      [
        "10768",
        "308",
        "2025-01-16",
        "14:59:01",
        "243",
        "2025-03-19",
        "15:01:43"
      ],
      [
        "8803",
        "307",
        "2025-01-17",
        "17:36:58",
        "327",
        "2025-03-05",
        "22:57:49"
      ]
    ]
  },
  "checked_utc": "2026-10-16T14:27:28.561097+00:00"
}
```

## 심화 검증 재현

실행 명령: `python scripts/collection/nubija_trips_quality_2025.py`. SQLite 3.50.4 (Python 표준라이브러리). 중복 검사는 7개 CSV 필드 전체의 일치 기준이며 SQLite 임시 DB에 순차 적재 후 GROUP BY로 정확히 계산했다. 임시 DB는 검증 종료 후 자동 삭제되며 원본은 수정하지 않았다. 메모리 적재 단위는 100,000행이다.

원본 출발/도착 터미널 값은 문자열 그대로 2025년 시트 터미널번호(문자열)와 비교하였다. 좌표 또는 명칭을 추정하여 결합하지 않았다. 코드7과329의 미일치 원인은 별도 역사자료 대조가 필요하다.

## 2024년 단독 재시도 완료

{
  "year": 2024,
  "path": "C:\\업무\\교통공모전\\data\\raw\\nubija_trips\\nubija_trips_2024.csv",
  "bytes": 245633968,
  "sha256": "8146617ccfa69430cfbb4c570b750df9456667dd72cba374b4396cee34e3a51f",
  "started_utc": "2026-10-16T14:23:53.922681+00:00",
  "finished_utc": "2026-10-16T14:29:17.407693+00:00",
  "download_url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003634157&fileDetailSn=1&insertDataPrcus=N"
}

### 전체 CSV 검증: nubija_trips_2024.csv

```json
{
  "entry": "nubija_trips_2024.csv",
  "encoding": "cp949",
  "records": 4582332,
  "columns": [
    "자전거번호",
    "출발터미널",
    "출발일",
    "출발시간",
    "도착터미널",
    "도착일",
    "도착시간"
  ],
  "missing_blank_cells": {
    "자전거번호": 0,
    "출발터미널": 0,
    "출발일": 0,
    "출발시간": 0,
    "도착터미널": 0,
    "도착일": 0,
    "도착시간": 0
  },
  "date_ranges_raw_strings": {
    "출발일": [
      "2024-01-01",
      "2024-12-31"
    ],
    "도착일": [
      "2024-01-01",
      "2025-03-14"
    ]
  },
  "monthly_counts": {
    "출발일": {
      "2024-01": 266303,
      "2024-02": 231958,
      "2024-03": 323303,
      "2024-04": 389277,
      "2024-05": 462603,
      "2024-06": 455505,
      "2024-07": 413583,
      "2024-08": 404761,
      "2024-09": 420495,
      "2024-10": 446170,
      "2024-11": 416558,
      "2024-12": 351816
    },
    "도착일": {
      "2024-01": 266253,
      "2024-02": 231958,
      "2024-03": 323253,
      "2024-04": 389265,
      "2024-05": 462559,
      "2024-06": 455584,
      "2024-07": 413527,
      "2024-08": 404718,
      "2024-09": 420505,
      "2024-10": 446214,
      "2024-11": 416565,
      "2025-03": 1,
      "2024-12": 351836,
      "2025-01": 94
    }
  },
  "unique_terminal_counts": {
    "출발터미널": 446,
    "도착터미널": 447
  },
  "first_3_records": [
    [
      "8114",
      "101",
      "2024-01-01",
      "00:00:18",
      "277",
      "2024-01-01",
      "03:17:20"
    ],
    [
      "9125",
      "81",
      "2024-01-01",
      "00:00:44",
      "106",
      "2024-01-01",
      "00:53:20"
    ],
    [
      "5174",
      "61",
      "2024-01-01",
      "00:01:03",
      "355",
      "2024-01-01",
      "00:10:34"
    ]
  ],
  "checked_utc": "2026-10-16T14:29:38.529375+00:00"
}
```

2025 터미널 XLSX 참조 읽기 엔진: openpyxl 3.1.5. station 원본은 읽기만 하였다.

## 2023년 단독 재시도 완료

{
  "year": 2023,
  "path": "C:\\업무\\교통공모전\\data\\raw\\nubija_trips\\nubija_trips_2023.csv",
  "bytes": 216640346,
  "sha256": "973f82b32803f9a72d26c845c2be6f5a783836881f603e81783c54561b3cad4b",
  "started_utc": "2026-10-16T14:29:17.409249+00:00",
  "finished_utc": "2026-10-16T14:33:25.407565+00:00",
  "download_url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003630519&fileDetailSn=1&insertDataPrcus=N"
}

### 전체 CSV 검증: nubija_trips_2023.csv

```json
{
  "entry": "nubija_trips_2023.csv",
  "encoding": "cp949",
  "records": 4066540,
  "columns": [
    "자전거번호",
    "출발터미널",
    "출발일",
    "출발시간",
    "도착터미널",
    "도착일",
    "도착시간"
  ],
  "missing_blank_cells": {
    "자전거번호": 0,
    "출발터미널": 0,
    "출발일": 0,
    "출발시간": 0,
    "도착터미널": 0,
    "도착일": 0,
    "도착시간": 0
  },
  "date_ranges_raw_strings": {
    "출발일": [
      "2023-01-01",
      "2023-12-31"
    ],
    "도착일": [
      "2023-01-01",
      "2024-01-04"
    ]
  },
  "monthly_counts": {
    "출발일": {
      "2023-01": 253391,
      "2023-02": 269237,
      "2023-03": 374016,
      "2023-04": 359148,
      "2023-05": 370112,
      "2023-06": 390938,
      "2023-07": 325296,
      "2023-08": 326641,
      "2023-09": 343248,
      "2023-10": 425205,
      "2023-11": 363277,
      "2023-12": 266031
    },
    "도착일": {
      "2023-01": 253324,
      "2023-02": 269220,
      "2023-09": 343204,
      "2023-03": 373969,
      "2023-07": 325363,
      "2023-04": 359178,
      "2023-05": 370087,
      "2023-06": 390920,
      "2023-10": 425226,
      "2023-08": 326635,
      "2023-11": 363331,
      "2023-12": 266018,
      "2024-01": 65
    }
  },
  "unique_terminal_counts": {
    "출발터미널": 346,
    "도착터미널": 347
  },
  "first_3_records": [
    [
      "6254",
      "42",
      "2023-01-01",
      "00:00:25",
      "42",
      "2023-01-01",
      "00:00:52"
    ],
    [
      "9660",
      "284",
      "2023-01-01",
      "00:01:13",
      "201",
      "2023-01-01",
      "00:08:49"
    ],
    [
      "6254",
      "42",
      "2023-01-01",
      "00:01:24",
      "124",
      "2023-01-01",
      "00:06:19"
    ]
  ],
  "checked_utc": "2026-10-16T14:33:44.097151+00:00"
}
```

## 단독 재시도 중단

{
  "year": 2022,
  "partial_bytes": 58458112,
  "error": "ChunkedEncodingError(ProtocolError('Connection broken: IncompleteRead(58499064 bytes read, 100504158 more expected)', IncompleteRead(58499064 bytes read, 100504158 more expected)))",
  "started_utc": "2026-10-16T14:33:25.408746+00:00",
  "finished_utc": "2026-10-16T14:37:25.700959+00:00",
  "download_url": "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002865115&fileDetailSn=1&insertDataPrcus=N"
}

## 2022년 재시도 부분파일 최종 확인

- 파일: C:\업무\교통공모전\data\raw\nubija_trips\nubija_trips_2022.zip.partial
- 수신 파일 크기: 58458112 bytes
- 서버 Content-Length: 159003222 bytes
- 부분 SHA256: b93c650e2fedb97b1355ef7485551c834b4616e6117f2665dd025bf99008016c
- 상태: 미완료. ZIP 중앙 디렉터리·전체 CRC·2022년 레코드 수·기간·결측 미검증. 정상 원본으로 사용하면 안 된다.
- 단독 전송 중 서버가 연결을 닫아 IncompleteRead가 발생했다. read timeout을 300초로 늘렸지만 timeout 이전에 연결이 종료되었다. Range 요청은 앞서 200 전체 응답으로 무시됨을 확인하여 덧붙이기 재개를 하지 않았다. 반복 재시도는 중단하고 부모에게 브라우저 대체 수집용 공식 URL을 전달했다.
- 공식 UI 경로: https://www.data.go.kr/data/15126280/fileData.do → 주기성 과거 데이터 → 경상남도 창원시_공영자전거 누비자 대여 반납 이력_20221231 → 데이터 다운로드 → ZIP.
- 최종 점검 UTC: 2026-10-16T14:37:57.387882+00:00

## 2022 ZIP 수집 종료 및 사람 할 일

부모가 Aside 브라우저 대체 다운로드도 시도했으나 브라우저/daemon 연결 종료로 실패했다고 전달하였다. 2022 ZIP 완성파일은 없으며 미완료 상태다. 더 이상 자동 다운로드를 재시도하지 않는다.

2022 완성파일을 기다리던 본 작업의 검증 세션 88788에만 Ctrl+C를 전송하였다. 도구가 exit_code 1로 해당 세션 종료를 반환했다. 다른 프로세스에는 종료 명령을 보내지 않았다. 완료된 2023~2025 검증 기록과 원본 및 모든 부분파일은 그대로 보존했다.

사람 할 일: 일반 브라우저에서 공공데이터포털 공식 페이지 → 주기성 과거 데이터 → 20221231 자료 → ZIP을 수동 다운로드한다. 기대 크기 159,003,222 bytes와 정상 ZIP 여부를 확인한 뒤 별도 검증을 요청한다. 파일 확보 전에는 2022 자료를 확보·검증했다고 표시하지 않는다.

공식 페이지: https://www.data.go.kr/data/15126280/fileData.do

공식 직접 URL: https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000002865115&fileDetailSn=1&insertDataPrcus=N

종료 기록 UTC: 2026-10-16T14:42:27.581994+00:00
