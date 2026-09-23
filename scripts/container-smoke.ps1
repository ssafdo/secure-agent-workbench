$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$imageId = & $docker image inspect --format "{{.Id}}" secure-agent-runner:dev
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($imageId)) {
    throw "The local secure-agent-runner:dev image is unavailable."
}

$env:PYTHONPATH = Join-Path $repositoryRoot "src"
$env:AGENT_WORKBENCH_CONTAINER_ENABLED = "true"
$env:AGENT_WORKBENCH_CONTAINER_IMAGE = $imageId.Trim()
$env:AGENT_WORKBENCH_CONTAINER_EXECUTABLES = "agent-runner"

Push-Location $repositoryRoot
try {
    python -m agent_workbench container-smoke
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
