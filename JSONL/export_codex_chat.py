#!/usr/bin/env python3
"""Export a Codex session JSONL to Markdown and styled offline HTML."""
import argparse
import base64
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
INJECTED = ("<environment_context>", "<recommended_plugins>", "<permissions instructions>")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def parse_session_id(value):
    value = value.strip()
    if value.lower().startswith("codex://"):
        parsed = urlparse(value)
        if parsed.scheme.lower() != "codex" or parsed.netloc.lower() != "threads":
            raise ValueError("Deeplink must be codex://threads/SESSION-ID")
        value = parsed.path.strip("/").split("/", 1)[0]
    if not UUID_RE.fullmatch(value):
        raise ValueError("Invalid session ID or deeplink: " + repr(value))
    return value.lower()


def codex_homes(override):
    values = []
    if override:
        values.append(override.expanduser())
    if os.environ.get("CODEX_HOME"):
        values.append(Path(os.environ["CODEX_HOME"]).expanduser())
    values.append(Path.home() / ".codex")
    result = []
    for value in values:
        value = value.resolve()
        if value not in result:
            result.append(value)
    return result


def find_session(sid, override):
    matches = []
    for home in codex_homes(override):
        for folder in (home / "sessions", home / "archived_sessions"):
            if folder.is_dir():
                matches.extend(folder.rglob("*" + sid + "*.jsonl"))
    matches = list(dict.fromkeys(path.resolve() for path in matches))
    if not matches:
        raise FileNotFoundError("No session JSONL found for " + sid)
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if len(matches) > 1:
        print("Warning: using newest match: " + str(matches[0]), file=sys.stderr)
    return matches[0]


def find_thread_name(sid, override):
    """Return the newest indexed Codex thread name, if one is available."""
    matches = []
    for home in codex_homes(override):
        index = home / "session_index.jsonl"
        if not index.is_file():
            continue
        with index.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("id") == sid and item.get("thread_name"):
                    matches.append(
                        (str(item.get("updated_at") or ""), str(item["thread_name"]))
                    )
    return max(matches, default=("", ""), key=lambda item: item[0])[1] or None


def safe_filename(value, maximum_length=150):
    """Convert a Codex thread title into a safe Windows filename stem."""
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        return "codex-chat"
    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = "_" + value
    return value[:maximum_length].rstrip(" .")


def normalize_math_for_markdown(text):
    """Convert LaTeX delimiters to the form commonly supported by Markdown."""
    output = []
    in_fence = False
    fence = chr(96) * 3
    for line in text.splitlines():
        if line.lstrip().startswith(fence):
            in_fence = not in_fence
            output.append(line)
            continue
        if not in_fence:
            line = line.replace(r"\[", "$$").replace(r"\]", "$$")
            line = line.replace(r"\(", "$").replace(r"\)", "$")
        output.append(line)
    return "\n".join(output)


def prompt_heading(item, number, maximum_length=120):
    """Create a concise Markdown outline heading from a user prompt."""
    text = next((value for kind, value in item["parts"] if kind == "text"), "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"^[\s#>*+\-\d.)]+", "", text)
    text = re.sub(r"[\x00-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "Prompt " + str(number)
    if len(text) > maximum_length:
        text = text[: maximum_length - 1].rstrip() + "…"
    return text


def load_jsonl(path):
    records = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError("Invalid JSON on line " + str(number)) from error
            if isinstance(value, dict):
                records.append(value)
    return records


def extract_metadata(records, sid):
    result = {"session_id": sid}
    for record in records:
        if record.get("type") != "session_meta":
            continue
        payload = record.get("payload") or {}
        result["session_id"] = str(
            payload.get("session_id") or payload.get("id") or sid
        )
        for key in ("timestamp", "cwd"):
            if payload.get(key):
                result[key] = str(payload[key])
        break
    return result


def save_image(data_url, assets, number):
    match = re.fullmatch(r"data:([^;,]+);base64,(.*)", data_url, re.DOTALL)
    if not match:
        return data_url
    media_type, encoded = match.groups()
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(media_type.lower(), ".bin")
    assets.mkdir(parents=True, exist_ok=True)
    filename = "image-" + str(number).zfill(3) + extension
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("Unable to decode attached image") from error
    (assets / filename).write_bytes(content)
    return "assets/" + filename


def extract_messages(records, assets, include_commentary):
    result = []
    image_number = 0
    for record in records:
        payload = record.get("payload") or {}
        if record.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        phase = payload.get("phase")
        if role not in ("user", "assistant"):
            continue
        if role == "assistant" and phase == "commentary" and not include_commentary:
            continue
        parts = []
        for item in payload.get("content") or []:
            kind = item.get("type")
            if kind in ("input_text", "output_text"):
                text = item.get("text") or ""
                lowered = text.lstrip().lower()
                if role == "user" and any(
                    lowered.startswith(prefix) for prefix in INJECTED
                ):
                    continue
                if text.strip():
                    parts.append(("text", text.rstrip()))
            elif kind == "input_image" and item.get("image_url"):
                image_number += 1
                source = item["image_url"]
                if source.startswith("data:"):
                    source = save_image(source, assets, image_number)
                parts.append(("image", source))
        if parts:
            result.append(
                {
                    "role": role,
                    "phase": phase,
                    "timestamp": str(record.get("timestamp") or ""),
                    "parts": parts,
                }
            )
    return result


def render_markdown(items, meta):
    lines = [
        "# " + meta.get("thread_name", "Codex conversation"),
        "",
        "- **Session ID:** " + meta["session_id"],
        "- **Deeplink:** codex://threads/" + meta["session_id"],
    ]
    if meta.get("timestamp"):
        lines.append("- **Started:** " + meta["timestamp"])
    if meta.get("cwd"):
        lines.append("- **Working directory:** " + meta["cwd"])
    lines += ["", "---", ""]
    image_number = 0
    prompt_number = 0
    for item in items:
        if item["role"] == "user":
            prompt_number += 1
            lines += ["## " + prompt_heading(item, prompt_number), "", "**You:**", ""]
        else:
            label = "Codex work log" if item["phase"] == "commentary" else "Codex"
            lines += ["**" + label + ":**", ""]
        for kind, value in item["parts"]:
            if kind == "text":
                lines += [normalize_math_for_markdown(value), ""]
            else:
                image_number += 1
                lines += [
                    "![Attached image " + str(image_number) + "](" + value + ")",
                    "",
                ]
        lines += ["---", ""]
    return "\n".join(lines).rstrip() + "\n"


def safe_link(url):
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() in ("javascript", "vbscript"):
        return "#"
    return html.escape(url.strip(), quote=True)


def inline_markdown(text):
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: '<a href="' + safe_link(html.unescape(match.group(2)))
        + '">' + match.group(1) + "</a>",
        escaped,
    )
    return escaped


def markdown_to_html(text):
    """Safe, dependency-free renderer for common chat Markdown."""
    output = []
    paragraph = []
    code = []
    math_lines = []
    list_type = None
    in_code = False
    math_close = None
    fence = chr(96) * 3

    def flush_paragraph():
        if paragraph:
            output.append(
                "<p>" + "<br>".join(inline_markdown(x) for x in paragraph) + "</p>"
            )
            paragraph.clear()

    def close_list():
        nonlocal list_type
        if list_type:
            output.append("</" + list_type + ">")
            list_type = None

    for line in text.splitlines():
        stripped = line.strip()
        if math_close:
            math_lines.append(line)
            if stripped == math_close:
                output.append(
                    '<div class="math-block">'
                    + html.escape("\n".join(math_lines))
                    + "</div>"
                )
                math_lines.clear()
                math_close = None
            continue
        if line.lstrip().startswith(fence):
            flush_paragraph()
            close_list()
            if in_code:
                output.append(
                    "<pre><code>" + html.escape("\n".join(code)) + "</code></pre>"
                )
                code.clear()
            in_code = not in_code
        elif in_code:
            code.append(line)
        elif stripped in (r"\[", "$$"):
            flush_paragraph()
            close_list()
            math_close = r"\]" if stripped == r"\[" else "$$"
            math_lines.append(line)
        elif not line.strip():
            flush_paragraph()
            close_list()
        elif re.match(r"^#{1,6}\s+", line):
            flush_paragraph()
            close_list()
            hashes, title = line.split(" ", 1)
            level = len(hashes)
            output.append(
                "<h" + str(level) + ">" + inline_markdown(title)
                + "</h" + str(level) + ">"
            )
        elif re.match(r"^\s*[-+*]\s+", line):
            flush_paragraph()
            if list_type != "ul":
                close_list()
                list_type = "ul"
                output.append("<ul>")
            value = re.sub(r"^\s*[-+*]\s+", "", line)
            output.append("<li>" + inline_markdown(value) + "</li>")
        elif re.match(r"^\s*\d+[.)]\s+", line):
            flush_paragraph()
            if list_type != "ol":
                close_list()
                list_type = "ol"
                output.append("<ol>")
            value = re.sub(r"^\s*\d+[.)]\s+", "", line)
            output.append("<li>" + inline_markdown(value) + "</li>")
        elif line.lstrip().startswith(">"):
            flush_paragraph()
            close_list()
            output.append(
                "<blockquote>" + inline_markdown(line.lstrip()[1:].lstrip())
                + "</blockquote>"
            )
        else:
            close_list()
            paragraph.append(line)
    if in_code:
        output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    if math_lines:
        output.append(
            '<div class="math-block">' + html.escape("\n".join(math_lines)) + "</div>"
        )
    flush_paragraph()
    close_list()
    return "\n".join(output)


def render_html(items, meta):
    cards = []
    for item in items:
        label = "You" if item["role"] == "user" else "Codex"
        body = []
        for kind, value in item["parts"]:
            if kind == "text":
                body.append(markdown_to_html(value))
            else:
                body.append(
                    '<img class="attachment" src="' + safe_link(value)
                    + '" alt="Attached image">'
                )
        extra = " commentary" if item["phase"] == "commentary" else ""
        stamp = html.escape(item["timestamp"])
        cards.append(
            '<article class="message ' + item["role"] + extra + '">'
            + "<header><b>" + label + "</b><time>" + stamp + "</time></header>"
            + '<div class="content">' + "".join(body) + "</div></article>"
        )
    sid = html.escape(meta["session_id"])
    title = html.escape(meta.get("thread_name", "Codex conversation"))
    style = """
:root{color-scheme:dark;--bg:#1f2329;--panel:#292e36;--text:#d7dce2;--muted:#929aa5;--line:#363c45;--code:#252a32;--link:#75a7ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,sans-serif}
main{max-width:1180px;margin:auto;padding:30px 34px 80px}.session{border-bottom:1px solid var(--line);margin-bottom:28px;padding-bottom:18px}
.session h1{font-size:20px;margin:0 0 8px}.session p{color:var(--muted);margin:3px 0;overflow-wrap:anywhere}
.message{margin:24px 0}.message.user{width:min(76%,900px);margin-left:auto;background:var(--panel);padding:13px 17px;border-radius:17px}
.message.assistant{width:min(94%,1060px);margin-right:auto}.message.commentary{opacity:.78;border-left:3px solid var(--line);padding-left:14px}
.message header{display:flex;justify-content:space-between;gap:15px;color:var(--muted);font-size:12px;margin-bottom:7px}
.content>:first-child{margin-top:0}.content>:last-child{margin-bottom:0}a{color:var(--link)}
pre{background:var(--code);border:1px solid var(--line);border-radius:9px;overflow:auto;padding:14px}
code{font-family:Consolas,monospace}.attachment{display:block;max-width:100%;height:auto;border:1px solid var(--line);border-radius:9px}
.math-block{margin:14px 0;overflow-x:auto;text-align:center}
blockquote{border-left:3px solid #667080;color:#bcc3cc;margin:12px 0;padding-left:14px}
@media(max-width:700px){main{padding:18px 14px 50px}.message.user,.message.assistant{width:100%}time{display:none}}
@media print{:root{color-scheme:light;--bg:white;--panel:#f0f1f3;--text:#111;--muted:#555;--line:#ccc;--code:#f4f4f4;--link:#0645ad}}
"""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + title + "</title><style>" + style
        + """</style>
<script>
window.MathJax = {
  tex: {
    inlineMath: [['\\(', '\\)'], ['$', '$']],
    displayMath: [['\\[', '\\]'], ['$$', '$$']],
    processEscapes: true
  },
  options: {skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']}
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"></script>
</head><body><main><section class="session">"""
        + "<h1>" + title + "</h1><p><b>Session ID:</b> " + sid
        + "</p><p><b>Deeplink:</b> codex://threads/" + sid
        + "</p></section>" + "".join(cards) + "</main></body></html>\n"
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Export a Codex session to Markdown and styled offline HTML."
    )
    parser.add_argument("session", help="Session UUID or codex://threads/UUID")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--include-commentary", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        sid = parse_session_id(args.session)
        source = find_session(sid, args.codex_home)
        output = args.output_dir.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        records = load_jsonl(source)
        meta = extract_metadata(records, sid)
        thread_name = find_thread_name(sid, args.codex_home)
        if thread_name:
            meta["thread_name"] = thread_name
        items = extract_messages(records, output / "assets", args.include_commentary)
        if not items:
            raise ValueError("No exportable user or assistant messages found")
        filename = safe_filename(thread_name or ("codex-chat-" + sid))
        base = output / filename
        markdown_path = base.with_suffix(".md")
        html_path = base.with_suffix(".html")
        markdown_path.write_text(render_markdown(items, meta), encoding="utf-8")
        html_path.write_text(render_html(items, meta), encoding="utf-8")
    except (OSError, ValueError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1
    print("Session source: " + str(source))
    print("Messages exported: " + str(len(items)))
    print("Markdown: " + str(markdown_path))
    print("HTML: " + str(html_path))
    if (output / "assets").is_dir():
        print("Assets: " + str(output / "assets"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
