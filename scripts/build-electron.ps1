# Compatibility wrapper; see maintenance/BUILD_RELEASE.md.
param([switch]$All, [switch]$Publish)
$ErrorActionPreference = "Stop"
if ($All -or $Publish) {
    Write-Error "Use the verified GitHub tag workflow for cross-platform publishing."
    exit 1
}
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
python (Join-Path $projectRoot "scripts/build_desktop.py")
exit $LASTEXITCODE
