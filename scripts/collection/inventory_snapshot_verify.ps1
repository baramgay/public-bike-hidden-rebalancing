# 보존 HTML만 읽는 검증·추출 명령. 네트워크 요청 없음.
param([string]$ProjectRoot='C:/업무/교통공모전')
$ErrorActionPreference='Stop'
$path="$ProjectRoot/data/raw/inventory/nubija_terminal_status_20261016.html"
$s=Get-Content -Raw -LiteralPath $path
# 페이지에서 터미널을 클릭할 때 표시되는 공개 값만 읽는다. 내부 API 주소 탐색/호출 없음.
$pattern='onclick="showMapInfoWindow\(([^\r\n]+)\)"'
$matches=[regex]::Matches($s,$pattern)
$rows=@(foreach($m in $matches){
    $argText=[Net.WebUtility]::HtmlDecode($m.Groups[1].Value)
    $vals=@([regex]::Matches($argText,"'([^']*)'")|ForEach-Object{$_.Groups[1].Value})
    if($vals.Count -eq 6){[pscustomobject]@{terminal_number=$vals[2];terminal_name=$vals[0];available_bikes=[int]$vals[1];latitude=[double]$vals[4];longitude=[double]$vals[5];page_saved_utc=(Get-Item $path).LastWriteTimeUtc.ToString('o')}}
})
$rows|Export-Csv -LiteralPath "$ProjectRoot/data/raw/inventory/nubija_terminal_status_20261016_extracted.csv" -NoTypeInformation -Encoding utf8
[pscustomobject]@{rows=$rows.Count;uniqueNumbers=@($rows.terminal_number|Sort-Object -Unique).Count;missingNames=@($rows|Where-Object{[string]::IsNullOrWhiteSpace($_.terminal_name)}).Count;invalidCoordinates=@($rows|Where-Object{$_.latitude -lt 34 -or $_.latitude -gt 36 -or $_.longitude -lt 127 -or $_.longitude -gt 130}).Count;negativeCounts=@($rows|Where-Object{$_.available_bikes -lt 0}).Count;zeroCount=@($rows|Where-Object{$_.available_bikes -eq 0}).Count;totalAvailable=($rows.available_bikes|Measure-Object -Sum).Sum;maxAvailable=($rows.available_bikes|Measure-Object -Maximum).Maximum;sourceSha=(Get-FileHash $path).Hash}|ConvertTo-Json -Compress
$rows|Group-Object terminal_number|Where-Object{$_.Count -gt 1}|ForEach-Object{$_.Group}|ConvertTo-Json -Compress
Get-ChildItem -LiteralPath "$ProjectRoot/data/raw/inventory" -File|ForEach-Object{[pscustomobject]@{name=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName).Hash;storedUtc=$_.LastWriteTimeUtc.ToString('o')}|ConvertTo-Json -Compress}
