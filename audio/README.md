# Audio notifications

The WAV files use the same built-in Windows speech voice as the original LLM notification. No network service or API key is needed.

## PowerShell

From this folder:

```powershell
.\script_initiated.ps1
.\script_completed.ps1
.\LLM_agent_complete.ps1
```

From anywhere:

```powershell
& 'H:\My Drive\VSCode_Github\AI_productivity_tools\audio\script_initiated.ps1'
& 'H:\My Drive\VSCode_Github\AI_productivity_tools\audio\script_completed.ps1'
```

Regenerate a file without playing it:

```powershell
.\script_initiated.ps1 -OutputWav "$PWD\script_initiated.wav" -NoPlay
```

The new PowerShell launchers play cached WAVs by default. They also support `-Rate` (-10 to 10), `-Volume` (0 to 100), and `-NoPlay`. The original LLM PowerShell script retains its speech-generation behavior.

## Bash (Git Bash, WSL, Linux, macOS)

From this folder:

```bash
bash ./script_initiated.sh
bash ./script_completed.sh
bash ./LLM_agent_complete.sh
```

Example around a script (completion sound plays only on success):

```bash
bash /path/to/audio/script_initiated.sh
python my_script.py && bash /path/to/audio/script_completed.sh
```

Windows and WSL use Windows PowerShell for playback. Linux/macOS use an installed player (`afplay`, `paplay`, `aplay`, or `ffplay`). Keep the WAV files beside the launchers for native playback.

### WSL when H: is not mounted

This machine's WSL currently cannot access H:. Copy the four `.sh` files to a WSL-accessible folder, then point them at the Windows audio directory:

```bash
export AUDIO_NOTIFICATION_DIR='H:\My Drive\VSCode_Github\AI_productivity_tools\audio'
bash ./script_initiated.sh
bash ./script_completed.sh
bash ./LLM_agent_complete.sh
```

Alternatively, once the H: drive is mounted in WSL, invoke the launchers directly from its mount path. `AUDIO_NOTIFICATION_DIR` can also select another audio directory.

## Agent completion preference

The user's global Codex `AGENTS.md` requests the existing LLM completion sound once just before each final response, using `play_notification.ps1 -Signal LLM_agent_complete`.
