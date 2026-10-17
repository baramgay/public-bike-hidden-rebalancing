# 수집 과정에서 사용한 PowerShell 명령을 재현용으로 보존한 스크립트.
# 실행하지 않고 보존했다. 모델/특징생성/데이터 정제는 수행하지 않는다.
param([string]$ProjectRoot = 'C:/업무/교통공모전')
$ErrorActionPreference = 'Stop'
foreach ($folder in @('weather','calendar','population')) {
    New-Item -ItemType Directory -Path "$ProjectRoot/data/raw/$folder" -Force | Out-Null
}
Invoke-WebRequest 'https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv' -OutFile "$ProjectRoot/data/raw/weather/noaa_isd_history.csv"
foreach ($yr in 2022..2025) {
    Invoke-WebRequest "https://www.ncei.noaa.gov/pub/data/noaa/$yr/471550-99999-$yr.gz" -OutFile "$ProjectRoot/data/raw/weather/isd_changwon_$yr.gz"
    Invoke-WebRequest "https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/$yr/47155099999.csv" -OutFile "$ProjectRoot/data/raw/weather/gsod_changwon_47155099999_$yr.csv"
    $page = Invoke-WebRequest "https://astro.kasi.re.kr/kor/life/post/calendarData?search_year=$yr"
    $page.Content | Set-Content -LiteralPath "$ProjectRoot/data/raw/calendar/kasi_calendarData_$yr.html" -Encoding utf8
    Invoke-WebRequest "https://astro.kasi.re.kr/kor/life/post/almanac?search_year=$yr" -OutFile "$ProjectRoot/data/raw/calendar/kasi_official_almanac_$yr.html"
    $match = [regex]::Match($page.Content,"downLocation\('([^']+)'")
    if ($match.Success) {
        $dest = "$ProjectRoot/data/raw/calendar/kasi_calendarData_$yr.txt"
        Invoke-WebRequest 'https://astro.kasi.re.kr/web-front/comm/fileDownload' -Method Post -Body @{file1="$yr 달력자료.txt";file2=$match.Groups[1].Value;path='/file'} -OutFile $dest
        if ((Get-Content -LiteralPath $dest -TotalCount 1) -match '<script|<!DOCTYPE|<html') {
            Move-Item -LiteralPath $dest -Destination "$ProjectRoot/data/raw/calendar/failed_txt_request_$yr.html" -Force
        }
    }
}
Invoke-WebRequest 'https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf' -OutFile "$ProjectRoot/data/raw/weather/isd-format-document.pdf"
Invoke-WebRequest 'https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt' -OutFile "$ProjectRoot/data/raw/weather/gsod_readme.txt"
Invoke-WebRequest 'https://www.data.go.kr/data/15057210/openapi.do' -OutFile "$ProjectRoot/data/raw/weather/kma_asos_hourly_catalog.html"
# 인구는 설명/실데이터 불일치 확인 후 추가 수집을 중단했다. 아래는 당시 사용한 공개 다운로드 주소이다.
# Invoke-WebRequest 'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007635996&fileDetailSn=1&insertDataPrcus=N' -OutFile "$ProjectRoot/data/raw/population/changwon_age_month_202101_202606.csv"
