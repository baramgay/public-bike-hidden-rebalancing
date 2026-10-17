# 수집 중 사용한 실제 검증 로직. 파일 실행 없이 명령으로 수행한 내용을 보존.
param([string]$ProjectRoot = 'C:/업무/교통공모전')
$ErrorActionPreference = 'Stop'
foreach ($yr in 2022..2025) {
    $path = "$ProjectRoot/data/raw/weather/isd_changwon_$yr.gz"
    $fs = [IO.File]::OpenRead($path)
    $gz = [IO.Compression.GzipStream]::new($fs,[IO.Compression.CompressionMode]::Decompress)
    $sr = [IO.StreamReader]::new($gz)
    $txt = $sr.ReadToEnd(); $sr.Dispose()
    $lines = @($txt -split "`n" | Where-Object {$_.Length -gt 0})
    $dates = @($lines | ForEach-Object {$_.Substring(15,12)})
    [pscustomobject]@{file="isd_changwon_$yr.gz";rows=$lines.Count;uniqueTimes=@($dates|Sort-Object -Unique).Count;nonHourly=@($dates|Where-Object {$_.Substring(10,2) -ne '00'}).Count;first=($dates|Sort-Object|Select-Object -First 1);last=($dates|Sort-Object|Select-Object -Last 1);size=(Get-Item $path).Length;sha256=(Get-FileHash $path).Hash} | ConvertTo-Json -Compress
    $path = "$ProjectRoot/data/raw/weather/gsod_changwon_47155099999_$yr.csv"
    $d = Import-Csv -LiteralPath $path
    [pscustomobject]@{year=$yr;rows=$d.Count;first=$d[0].DATE;last=$d[-1].DATE;missingTEMP=@($d|Where-Object {[double]$_.TEMP -eq 9999.9}).Count;missingPRCP=@($d|Where-Object {[double]$_.PRCP -eq 99.99}).Count} | ConvertTo-Json -Compress
}
$popPath = "$ProjectRoot/data/raw/population/changwon_age_month_202101_202606.csv"
if (Test-Path -LiteralPath $popPath) {
    $rows = Import-Csv -LiteralPath $popPath
    [pscustomobject]@{rows=$rows.Count;months=($rows.연월|Sort-Object -Unique);regions=($rows.행정구역|Sort-Object -Unique).Count} | ConvertTo-Json -Compress
}
foreach ($folder in @('weather','calendar','population')) {
    Get-ChildItem -LiteralPath "$ProjectRoot/data/raw/$folder" -File | ForEach-Object {
        [pscustomobject]@{path="$folder/$($_.Name)";bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName).Hash;storedUtc=$_.LastWriteTimeUtc.ToString('o')} | ConvertTo-Json -Compress
    }
}

