# Установка скилла reels-montage на Windows.
# Запуск: правый клик по файлу → «Выполнить с помощью PowerShell»
# или в терминале:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = Join-Path $env:USERPROFILE ".claude\skills\reels-montage"

Write-Host "1/4 Проверяю Python..."
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue) }
if (-not $py -or $py.Source -like "*WindowsApps*") {
    Write-Host "   Python не найден - ставлю через winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    Write-Host "   ПЕРЕЗАПУСТИТЕ терминал и запустите setup.ps1 ещё раз." -ForegroundColor Yellow
    exit 0
}
$pyexe = $py.Source

Write-Host "2/4 Проверяю FFmpeg..."
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    Write-Host "   FFmpeg установлен. После окончания установки перезапустите терминал." -ForegroundColor Yellow
}

Write-Host "3/4 Ставлю Python-библиотеки (faster-whisper, pillow, numpy)..."
& $pyexe -m pip install --upgrade pip | Out-Null
& $pyexe -m pip install -r (Join-Path $src "requirements.txt")

Write-Host "4/4 Копирую скилл в $dst ..."
if ((Resolve-Path $src).Path -ne $dst) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
}

Write-Host ""
Write-Host "Готово! Откройте Claude Code в папке с видео и напишите:" -ForegroundColor Green
Write-Host '  смонтируй рилс из видео.mp4, кодовое слово САЙТ' -ForegroundColor Green
