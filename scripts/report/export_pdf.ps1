# PPTX → PDF (설치된 PowerPoint로 내보내기). 사용: powershell -File export_pdf.ps1 <in.pptx> <out.pdf>
param([Parameter(Mandatory = $true)][string]$InPath, [Parameter(Mandatory = $true)][string]$OutPath)
$ErrorActionPreference = 'Stop'
$in = (Resolve-Path $InPath).Path
$out = [System.IO.Path]::GetFullPath($OutPath)
$app = New-Object -ComObject PowerPoint.Application
try {
    # 창 없이 열기: ReadOnly=1, Untitled=0, WithWindow=0
    $pres = $app.Presentations.Open($in, 1, 0, 0)
    try {
        $pres.SaveAs($out, 32)   # 32 = ppSaveAsPDF
    } finally {
        $pres.Close()
    }
} finally {
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
Write-Output "saved $out"
