# Codex JSONL chat exporter

Exports a local Codex session to Markdown, styled offline HTML, and an assets
folder for attached images. Message roles come from JSONL automatically.
The Markdown and HTML filenames use the latest chat title from Codex's local
session index. Characters that Windows does not permit in filenames are
replaced with hyphens. If no indexed title exists, the session ID is used.

## Usage

    python .\export_codex_chat.py SESSION_OR_DEEPLINK OUTPUT_DIRECTORY

Examples:

    python .\export_codex_chat.py 01a0cacf-96b5-7d51-b23e-d5b32997ad28 "H:\Exports\Codex chat"
    python .\export_codex_chat.py "codex://threads/01a0cacf-96b5-7d51-b23e-d5b32997ad28" "H:\Exports\Codex chat"

Options:

    --include-commentary   Include Codex work-log messages
    --codex-home PATH      Override the default ~/.codex location

No third-party packages or internet connection are required. Tool calls,
internal reasoning, developer instructions, and injected environment/plugin
metadata are excluded.

Markdown math delimiters are normalized to dollar-delimited LaTeX. In the
Markdown outline, each level-two heading is generated from the corresponding
user prompt; Codex response labels are bold text rather than headings.

The HTML file loads pinned MathJax 3.2.2 from jsDelivr to render LaTeX. Opening
the HTML therefore requires internet access for equation rendering; the rest of
the transcript and local image assets remain usable without it.
