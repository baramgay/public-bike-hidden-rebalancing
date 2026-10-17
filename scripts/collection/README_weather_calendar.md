# 날씨·달력 수집 재현

원래 수집과 검증은 PowerShell의 Invoke-WebRequest, Import-Csv, Get-FileHash 및 .NET GzipStream을 인라인 명령으로 실행했다. 그 명령들을 두 PS1에 보존했다. 다운로드한 파일은 실행하지 않았다. 보존한 PS1 자체도 이번 작업에서는 실행하지 않았다.

- weather_calendar_collect.ps1: 공개 무인증 다운로드 명령. 재실행하면 동일 경로 파일을 다시 받으므로 현재 SHA-256은 달라질 수 있다. 출처가 갱신되면 현재 보존본을 먼저 복사한다.
- weather_calendar_verify.ps1: 읽기 전용 파일 수·기간·일별 결측·해시 검사. 결과는 표준출력 JSON이다. 모델 구현·변환·보간은 없다.
- 원자료·실측 결과·실패 응답·한계는 data/metadata/weather_calendar_population.md에 있다.

재현명령(PowerShell 7):

    pwsh -NoProfile -File scripts/collection/weather_calendar_verify.ps1 -ProjectRoot C:/업무/교통공모전
    pwsh -NoProfile -File scripts/collection/weather_calendar_collect.ps1 -ProjectRoot C:/업무/교통공모전

수집 스크립트는 향후 재현용으로, 검증 스크립트는 기존 파일 확인용으로 구별한다. Python 패키지·외부 패키지 의존성은 없다. GSOD는 °F/knot/inch, ISD는 UTC·고정폭·품질코드를 주의한다. 2025는 8월24일 종료하며 달력 임시공휴일 보완과 과거 인구 품질문제가 미해결이다.
실제 실행환경: PowerShell 7.6.7; .NET 10.0.13; Windows.

