# Подключение инструментов из рилсов к Claude Code на Windows.
# Запуск из PowerShell:
#   powershell -ExecutionPolicy Bypass -File install-ai-tools.ps1            # основное: дизайн сайтов
#   powershell -ExecutionPolicy Bypass -File install-ai-tools.ps1 -Blender   # + Blender MCP (3D)
#   powershell -ExecutionPolicy Bypass -File install-ai-tools.ps1 -Voice     # + Chatterbox (озвучка текста)
#   powershell -ExecutionPolicy Bypass -File install-ai-tools.ps1 -ThreeD    # + img2threejs (3D-модель из фото)
#   powershell -ExecutionPolicy Bypass -File install-ai-tools.ps1 -Animation # + скиллы анимации и рисования для видео
# Можно комбинировать: -Blender -Voice -ThreeD -Animation

param([switch]$Blender, [switch]$Voice, [switch]$ThreeD, [switch]$Animation)
$ErrorActionPreference = "Stop"

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

Step "Node.js (нужен для npx, версия 22+)"
if (-not (Have node)) {
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    Write-Host "Node установлен. ПЕРЕЗАПУСТИТЕ PowerShell и запустите скрипт ещё раз." -ForegroundColor Yellow
    exit 0
}
$nodeMajor = [int]((node -v).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 22) { Write-Host "Node $(node -v) старый, Taste Skill нужен 22+: winget upgrade OpenJS.NodeJS.LTS" -ForegroundColor Yellow }

Step "1/4 Playwright CLI — Claude сам открывает сайт в браузере, кликает и делает скриншоты"
npm install -g @playwright/cli@latest
playwright-cli install --skills --global

Step "2/4 Impeccable — словарь и проверки дизайна (+ автопроверка после каждой правки)"
npx --yes impeccable@latest install --providers=claude --scope=global -y

Step "3/4 Taste Skill — правила вкуса, чтобы сайт не выглядел как AI-шаблон"
npx --yes skills@latest add https://github.com/Leonxlnx/taste-skill --skill design-taste-frontend -g -y -a claude-code

Step "4/4 Awesome DESIGN.md — готовые дизайн-системы известных сайтов"
Write-Host "Ставить не нужно: это библиотека файлов. Скажите Claude в проекте сайта:"
Write-Host '  "возьми DESIGN.md сайта apple из github.com/VoltAgent/awesome-design-md и сделай страницу в этом стиле"'

if ($ThreeD) {
    Step "img2threejs — 3D-модель из фотографии (нужны Git и Python 3.10+)"
    npx --yes img2threejs@latest install
    npx --yes img2threejs@latest doctor
}

if ($Blender) {
    Step "Blender MCP — Claude управляет Blender и делает 3D-рендеры"
    if (-not (Have blender) -and -not (Test-Path "C:\Program Files\Blender Foundation")) {
        winget install -e --id BlenderFoundation.Blender --accept-package-agreements --accept-source-agreements
    }
    if (-not (Have uvx)) {
        winget install -e --id astral-sh.uv --accept-package-agreements --accept-source-agreements
        Write-Host "uv установлен. ПЕРЕЗАПУСТИТЕ PowerShell и запустите скрипт ещё раз с -Blender." -ForegroundColor Yellow
        exit 0
    }
    uvx mcp-for-blender setup
    Write-Host "Откройте Blender: аддон сам запустит сервер (вкладка MCP for Blender, клавиша N в окне 3D)."
}

if ($Animation) {
    $skills = Join-Path $env:USERPROFILE ".claude\skills"
    New-Item -ItemType Directory -Force -Path $skills | Out-Null
    $repoSkills = Join-Path (Split-Path $PSScriptRoot -Parent) "skills"

    Step "Мои скиллы: video-director (режиссёр) и reels-montage (монтаж) -> $skills"
    foreach ($n in "video-director", "reels-montage") {
        Copy-Item -Path (Join-Path $repoSkills $n) -Destination $skills -Recurse -Force
    }
    python -m pip install -r (Join-Path $skills "reels-montage\requirements.txt")

    Step "Claude Drawing — картина рисуется кодом, 83 стиля (укиё-э, тушь, акварель)"
    $cd = Join-Path $skills "claude-drawing"
    if (Test-Path $cd) { git -C $cd pull --ff-only } else { git clone --depth 1 https://github.com/cloveric/claude-drawing-skill.git $cd }
    python -m pip install -r (Join-Path $cd "requirements.txt")

    Step "Huashu Art Motion — живые картины и кинопереходы (36 стилей, документация на китайском)"
    if (-not (Have uv)) { winget install -e --id astral-sh.uv --accept-package-agreements --accept-source-agreements }
    npx --yes skills@latest add alchaincyf/huashu-art-motion -g -y -a claude-code
    if (Have uv) { uv run --with playwright playwright install chromium }
    else { Write-Host "uv только что установлен: перезапустите PowerShell и выполните: uv run --with playwright playwright install chromium" -ForegroundColor Yellow }

    Step "Claude Animation Base — стартовый проект акварельных мультиков (p5.js + p5.brush)"
    $cab = "C:\Claude\ClaudeAnimationBase"
    if (-not (Test-Path $cab)) { git clone --depth 1 https://github.com/JohnHeibel/ClaudeAnimationBase.git $cab }
    Push-Location $cab; npm install; Pop-Location

    Step "Anidoodle — рисованные мультики, таймлапсы и надписи кистью"
    Write-Host "Это плагин: внутри Claude Code выполните две команды:" -ForegroundColor Yellow
    Write-Host "  /plugin marketplace add alexgreensh/anidoodle"
    Write-Host "  /plugin install anidoodle@alexgreensh-anidoodle"
}

if ($Voice) {
    Step "Chatterbox — озвучка текста, есть русский (тяжёлый: ~3-5 ГБ, без видеокарты NVIDIA медленно)"
    python -m pip install chatterbox-tts
}

Write-Host "`nГотово. Полностью закройте и заново откройте Claude Code." -ForegroundColor Green
Write-Host "Проверка внутри Claude Code: команда /skills должна показать playwright-cli, impeccable, design-taste-frontend."
