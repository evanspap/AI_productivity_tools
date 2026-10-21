[CmdletBinding()]
param(
    [string]$OutputWav,
    [ValidateRange(-10, 10)][int]$Rate = 0,
    [ValidateRange(0, 100)][int]$Volume = 100,
    [switch]$NoPlay
)
& (Join-Path $PSScriptRoot 'play_notification.ps1') -Signal 'script_completed' @PSBoundParameters
