# Accept the original CLI arguments, including --config, without PowerShell parameter binding.
$ErrorActionPreference = 'Continue'
# Keep native stderr progress/nonzero business exits from becoming PowerShell exceptions.
$PSNativeCommandUseErrorActionPreference = $false
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$flowScript = Join-Path $PSScriptRoot 'flow_api.py'
$flowArgs = @($args)
$flowCandidates = @(
    @{ Name = 'py'; Prefix = @('-3') },
    @{ Name = 'python'; Prefix = @() },
    @{ Name = 'python3'; Prefix = @() },
    @{ Name = (Join-Path $env:USERPROFILE '.config\bc-flow-api\venv\Scripts\python.exe'); Prefix = @() }
)
foreach ($candidate in $flowCandidates) {
    $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { continue }
    # Skip Microsoft Store execution aliases; probing them can open the Store UI.
    if ($command.Source -match '\\Microsoft\\WindowsApps\\python(?:3)?\.exe$') { continue }
    $prefix = $candidate.Prefix
    try {
        & $command.Source @prefix -I -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { continue }
    } catch { continue }
    if ($MyInvocation.ExpectingInput) {
        $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $input | & $command.Source @prefix $flowScript @flowArgs
    } else {
        & $command.Source @prefix $flowScript @flowArgs
    }
    exit $LASTEXITCODE
}
[Console]::Error.WriteLine('No working Python 3.9+ found. Install Python from https://www.python.org/downloads/ (enable PATH or the Python launcher), reopen the terminal, and rerun. keyring will be prepared automatically; no API request was sent.')
exit 2
