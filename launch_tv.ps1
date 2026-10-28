# Opens TradingView Desktop with the debug port (9222) CSO Live reads the chart through. Skips if it is already up.
try { Invoke-WebRequest http://127.0.0.1:9222/json/version -UseBasicParsing -TimeoutSec 1 | Out-Null; exit 0 } catch {}
Stop-Process -Name TradingView -Force -ErrorAction SilentlyContinue
Start-Sleep 1
$p = Get-AppxPackage *TradingView* | Select-Object -First 1
if ($p) {   # Microsoft Store install: a plain Start-Process of its exe exits silently
    Invoke-CommandInDesktopPackage -PackageFamilyName $p.PackageFamilyName -AppId 'TradingView.Desktop' `
        -Command "$($p.InstallLocation)\TradingView.exe" -Args '--remote-debugging-port=9222'
} else {
    $exe = @("$env:LOCALAPPDATA\Programs\TradingView\TradingView.exe", "$env:ProgramFiles\TradingView\TradingView.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) { Write-Host 'TradingView Desktop not found. Install it from tradingview.com/desktop'; exit 1 }
    Start-Process $exe '--remote-debugging-port=9222'
}
foreach ($i in 1..20) {
    Start-Sleep 1
    try { Invoke-WebRequest http://127.0.0.1:9222/json/version -UseBasicParsing -TimeoutSec 1 | Out-Null
          Write-Host 'TradingView is up in debug mode. Open a CME_MINI:NQ1! 1-minute chart.'; exit 0 } catch {}
}
Write-Host 'TradingView did not open its debug port (9222). Close it fully and run start.bat again.'
