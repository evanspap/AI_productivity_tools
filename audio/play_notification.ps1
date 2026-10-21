[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('LLM_agent_complete', 'script_initiated', 'script_completed')]
    [string]$Signal,
    [string]$OutputWav,
    [ValidateRange(-10, 10)][int]$Rate = 0,
    [ValidateRange(0, 100)][int]$Volume = 100,
    [switch]$NoPlay
)
$ErrorActionPreference = 'Stop'
$wavPath = Join-Path $PSScriptRoot "$Signal.wav"
if ($OutputWav -or $Rate -ne 0 -or $Volume -ne 100 -or -not (Test-Path -LiteralPath $wavPath)) {
    $messages = @{
        LLM_agent_complete = 'LLM agent complete'
        script_initiated = 'script initiated'
        script_completed = 'script completed'
    }
    & (Join-Path $PSScriptRoot 'LLM_agent_complete.ps1') -Message $messages[$Signal] -OutputWav $OutputWav -Rate $Rate -Volume $Volume -NoPlay:$NoPlay
}
elseif (-not $NoPlay) {
    $player = [System.Media.SoundPlayer]::new($wavPath)
    try { $player.Load(); $player.PlaySync() }
    finally { $player.Dispose() }
}
