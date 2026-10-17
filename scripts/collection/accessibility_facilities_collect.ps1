# 실제 수행한 공개 파일 수집 명령 보존. 실행하면 같은 경로를 덮어쓰므로 재현 전 보존본을 복사한다.
param([string]$ProjectRoot='C:/업무/교통공모전')
$ErrorActionPreference='Stop'
$root="$ProjectRoot/data/raw/accessibility_facilities"
New-Item -ItemType Directory -Path $root -Force|Out-Null
$items=@(
@{id='15088969';file='changwon_uichang_seongsan_medical_20251117.csv';atch='FILE_000000003540355'},
@{id='15088971';file='changwon_uichang_seongsan_pharmacy_20260514.csv';atch='FILE_000000003640543'},
@{id='15055453';file='changwon_masan_medical_20260101.csv';atch='FILE_000000003592030'},
@{id='15047970';file='changwon_market_fire_facilities_2026.csv';atch='FILE_000000003597042'},
@{id='15012894';file='nationwide_traditional_markets_20251110.csv';atch='FILE_000000003534420'}
)
foreach($x in $items){
$url="https://www.data.go.kr/data/$($x.id)/fileData.do"
if($x.id -eq '15012894'){$url="https://www.data.go.kr/data/$($x.id)/standard.do"}
$p=Invoke-WebRequest $url
$p.Content|Set-Content -LiteralPath "$root/catalog_$($x.id).html" -Encoding utf8
$download='https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId='+$x.atch+'&fileDetailSn=1&insertDataPrcus=N'
Invoke-WebRequest $download -OutFile (Join-Path $root $x.file)
}
# 시장 첨부 ID는 표준데이터 페이지에 공개적으로 연결된 상세팝업에서 확인했다.
$url='https://www.data.go.kr/tcs/dss/selectDpkDetailInfo.do?publicDataDetailPk=uddi:82d3ebec-6459-4127-86ef-f9134289471a_201904041007'
(Invoke-WebRequest $url).Content|Set-Content -LiteralPath "$root/market_detail.html" -Encoding utf8
# HIRA는 목록만 확보했다. 아래 공개 UI에 ZIP이 있으나 직접 경로는404였다. 재현 코드에서 실패 다운로드를 반복하지 않는다.
(Invoke-WebRequest 'https://www.data.go.kr/data/15051059/fileData.do').Content|Set-Content -LiteralPath "$root/catalog_15051059.html" -Encoding utf8
(Invoke-WebRequest 'https://opendata.hira.or.kr/op/opc/selectOpenData.do?sno=11925').Content|Set-Content -LiteralPath "$root/hira_11925.html" -Encoding utf8
