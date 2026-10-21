#!/usr/bin/env bash
# Play a cached notification; Windows/WSL use Windows audio output.
set -euo pipefail
signal=${1:-}
if (( $# > 0 )); then shift; fi
case "$signal" in
    LLM_agent_complete|script_initiated|script_completed) ;;
    *) printf 'Usage: bash play_notification.sh {LLM_agent_complete|script_initiated|script_completed}\n' >&2; exit 2 ;;
esac
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
audio_dir=${AUDIO_NOTIFICATION_DIR:-$script_dir}
ps_command=''
if command -v powershell.exe >/dev/null 2>&1; then
    ps_command=powershell.exe
elif [[ -x /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe ]]; then
    ps_command=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
fi
if [[ -n "$ps_command" ]]; then
    ps_file="$audio_dir/play_notification.ps1"
    case "$ps_file" in
        [a-zA-Z]:*|\\*) ;; # Already a Windows path.
        *)
            if command -v cygpath >/dev/null 2>&1; then
                ps_file=$(cygpath -w "$ps_file")
            elif command -v wslpath >/dev/null 2>&1; then
                ps_file=$(wslpath -w "$ps_file")
            fi
            ;;
    esac
    exec "$ps_command" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$ps_file" -Signal "$signal" "$@"
fi
if (( $# > 0 )); then
    printf 'Extra PowerShell options are supported only on Windows or WSL.\n' >&2
    exit 2
fi
wav="$audio_dir/$signal.wav"
[[ -f "$wav" ]] || { printf 'Audio file not found: %s\n' "$wav" >&2; exit 1; }
if command -v afplay >/dev/null 2>&1; then
    exec afplay "$wav"
elif command -v paplay >/dev/null 2>&1; then
    exec paplay "$wav"
elif command -v aplay >/dev/null 2>&1; then
    exec aplay "$wav"
elif command -v ffplay >/dev/null 2>&1; then
    exec ffplay -nodisp -autoexit -loglevel error "$wav"
else
    printf 'No audio player found. Install afplay, paplay, aplay, or ffplay.\n' >&2
    exit 1
fi
