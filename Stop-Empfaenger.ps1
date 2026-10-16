$taskRoot = $PSScriptRoot
$metadataPath = Join-Path $taskRoot 'diagnostics\receiver_process.json'
if (-not (Test-Path -LiteralPath $metadataPath)) {
    Write-Output 'Kein von Codex gestarteter Hintergrund-Empfaenger vermerkt. Konsolenempfaenger mit Strg+C beenden.'
    exit
}
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
$receiverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($metadata.pid)"
$expectedScript = Join-Path $taskRoot 'audio_receiver.py'
if ($receiverProcess -and $receiverProcess.Name -match '^python(w)?[.]exe$' -and $receiverProcess.CommandLine.Contains($expectedScript)) {
    Stop-Process -Id $metadata.pid
    Write-Output 'Hintergrund-Empfaenger beendet.'
} else {
    Write-Output 'Der vermerkte Hintergrund-Empfaenger laeuft nicht mehr.'
}
