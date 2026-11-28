# Подключает скиллы видео на этом компьютере НАПРЯМУЮ к репозиторию (без копий),
# чтобы любые улучшения приходили одним git pull — и уходили обратно одним push.
# Запуск из папки проекта:  powershell -ExecutionPolicy Bypass -File .claude\setup\sync-skills.ps1

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$userSkills = Join-Path $env:USERPROFILE ".claude\skills"
New-Item -ItemType Directory -Force -Path $userSkills | Out-Null

Write-Host "1/2 Подтягиваю изменения из GitHub..." -ForegroundColor Cyan
git -C $repo pull --ff-only

Write-Host "2/2 Подключаю скиллы к репозиторию (ссылки-«ярлыки» на папки)..." -ForegroundColor Cyan
foreach ($n in "reels-montage", "video-director") {
    $target = Join-Path $repo ".claude\skills\$n"
    $link = Join-Path $userSkills $n
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -eq "Junction") { Write-Host "   $n — уже подключён"; continue }
        $backup = "$link.old-copy"
        if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
        Rename-Item $link $backup
        Write-Host "   старая копия $n сохранена как $backup"
    }
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    Write-Host "   $n -> $target"
}
Write-Host "`nГотово. Дальше для обновления скиллов достаточно: git pull" -ForegroundColor Green
