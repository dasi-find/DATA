$ErrorActionPreference = "Stop"

$repositoryPath = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPython = Join-Path $repositoryPath ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $pythonCommand = $venvPython
    $pythonPrefixArgs = @()
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonPrefixArgs = @("-3")
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
    $pythonPrefixArgs = @()
}
else {
    Write-Host "Python 3을 찾지 못했습니다." -ForegroundColor Red
    Write-Host "Python을 설치하거나 .venv를 만든 뒤 다시 실행해 주세요."
    exit 1
}

Push-Location -LiteralPath $repositoryPath
try {
    & $pythonCommand @pythonPrefixArgs -m collectors.portal_institution --rows 20 --pages 1
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -eq 0) {
    Write-Host "data\processed 폴더에 CSV와 JSON을 저장했습니다." -ForegroundColor Green
}
else {
    Write-Host "위 오류와 .env 설정을 확인해 주세요." -ForegroundColor Yellow
}

exit $exitCode

