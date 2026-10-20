# 공식 status 페이지를 1회 읽어 보존한 실제 명령. 반복 폴링하지 않는다.
# 이용조건 재확인 전 이 수집 부분을 다시 실행하지 않는다.
param([string]$ProjectRoot='.')
$ErrorActionPreference='Stop'
$folder="$ProjectRoot/data/raw/inventory"
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$u='https://www.nubija.com/terminal/status'
$p=Invoke-WebRequest $u
[IO.File]::WriteAllText("$folder/nubija_terminal_status_20261016.html",$p.Content,[Text.UTF8Encoding]::new($false))
$p.Headers | ConvertTo-Json | Set-Content -LiteralPath "$folder/status_response_headers.json" -Encoding utf8
# 아래는 공개 robots/연결된 약관 각 1회 보존.
foreach($x in @(@{name='robots.txt';url='https://www.nubija.com/robots.txt'},@{name='terms_bike_use.html';url='https://www.nubija.com/terms/bike_use'},@{name='lepopark_linked_privacy_policy.html';url='https://www.lepopark.or.kr/contents/etc/etc01'})){
    $r=Invoke-WebRequest $x.url
    [IO.File]::WriteAllText((Join-Path $folder $x.name),$r.Content,[Text.UTF8Encoding]::new($false))
}
