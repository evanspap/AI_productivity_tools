[CmdletBinding()]
param(
    [string]$Message = "LLM agent complete",
    [string]$OutputWav,
    [ValidateRange(-10, 10)]
    [int]$Rate = 0,
    [ValidateRange(0, 100)]
    [int]$Volume = 100,
    [switch]$NoPlay
)

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Speech
    $speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    try {
        $speaker.Rate = $Rate
        $speaker.Volume = $Volume
        if ($OutputWav) {
            $wavPath = [System.IO.Path]::GetFullPath($OutputWav)
            $wavFolder = [System.IO.Path]::GetDirectoryName($wavPath)
            if ($wavFolder -and -not [System.IO.Directory]::Exists($wavFolder)) {
                [System.IO.Directory]::CreateDirectory($wavFolder) | Out-Null
            }
            $speaker.SetOutputToWaveFile($wavPath)
            $speaker.Speak($Message)
            $speaker.SetOutputToDefaultAudioDevice()
            if (-not $NoPlay) {
                $player = [System.Media.SoundPlayer]::new($wavPath)
                try { $player.PlaySync() }
                finally { $player.Dispose() }
            }
            Write-Output $wavPath
        }
        elseif (-not $NoPlay) {
            $speaker.Speak($Message)
        }
    }
    finally { $speaker.Dispose() }
}
catch {
    Write-Error "Could not generate the completion sound: $($_.Exception.Message)"
    exit 1
}
