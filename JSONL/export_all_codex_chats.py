#!/usr/bin/env python3
"""Archive local Codex sessions, including all recorded events, without APIs."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re
import sys

import export_codex_chat as chat


def event_text(record):
    # JSON preserves unknown fields, stored summaries and opaque/encrypted data.
    value = json.dumps(record, ensure_ascii=False, indent=2)
    runs = [len(match.group()) for match in re.finditer(r"`+", value)]
    fence = "`" * max(3, max(runs, default=0) + 1)
    return fence + "json\n" + value + "\n" + fence


def export_session(source, output, codex_home, full=True):
    # One snapshot keeps the rendered exports and raw archive consistent.
    snapshot = source.read_bytes()
    records = []
    warnings = []
    lines = snapshot.decode("utf-8-sig").split("\n")
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"Malformed or incomplete JSONL line {number}; retained in original.jsonl")
            continue
        if isinstance(record, dict):
            records.append(record)
    meta = chat.extract_metadata(records, source.stem)
    sid = meta["session_id"]
    if not chat.UUID_RE.fullmatch(sid):
        raise ValueError(f"Missing valid session ID: {source}")
    title = chat.find_thread_name(sid, codex_home) or "codex-chat-" + sid
    meta["thread_name"] = title
    # Full UUID prevents collisions for identical or sanitized chat titles.
    directory = output / (chat.safe_filename(title, 85) + " -- " + sid)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "original.jsonl").write_bytes(snapshot)
    items = []
    for record in records:
        payload = record.get("payload") or {}
        visible = chat.extract_messages([record], directory / "assets", True)
        # Extract images once across the entire session below to avoid collisions.
        if visible:
            items.extend(visible)
        elif full:
            kind = str(record.get("type", "event"))
            subtype = str(payload.get("type", "")) if isinstance(payload, dict) else ""
            items.append({
                "role": "assistant", "phase": "commentary",
                "timestamp": str(record.get("timestamp") or ""),
                "parts": [("text", "**Recorded event: " + kind + " / " + subtype + "**\n\n" + event_text(record))],
            })
    # Re-extract all visible messages together to allocate unique image filenames.
    visible = iter(chat.extract_messages(records, directory / "assets", True))
    for index, item in enumerate(items):
        if not item.get("parts", [("", "")])[0][1].startswith("**Recorded event:"):
            items[index] = next(visible)
    stem = chat.safe_filename(title, 100)
    md = directory / (stem + ".md")
    page = directory / (stem + ".html")
    md.write_text(chat.render_markdown(items, meta), encoding="utf-8")
    page.write_text(chat.render_html(items, meta), encoding="utf-8")
    counts = Counter(str(record.get("type", "unknown")) for record in records)
    result = {"session_id": sid, "title": title, "directory": directory.name,
              "source": str(source), "records": len(records), "event_types": dict(counts),
              "warnings": warnings, "html": str(page.relative_to(output))}
    (directory / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--source-dir", type=Path, help="Search this local JSONL folder recursively instead")
    parser.add_argument("--session", help="Export only this UUID or Codex deeplink")
    parser.add_argument("--readable-only", action="store_true", help="Omit raw events from MD/HTML; original JSONL is always retained")
    args = parser.parse_args(argv)
    output = args.output_dir.expanduser().resolve()
    if args.session:
        sources = [chat.find_session(chat.parse_session_id(args.session), args.codex_home)]
    else:
        roots = [args.source_dir.expanduser().resolve()] if args.source_dir else [
            home / name for home in chat.codex_homes(args.codex_home)
            for name in ("sessions", "archived_sessions")]
        sources = sorted({p.resolve() for root in roots if root.is_dir() for p in root.rglob("*.jsonl")
                          if output != p.parent and output not in p.parents})
    if not sources:
        parser.error("No local session JSONL files found")
    output.mkdir(parents=True, exist_ok=True)
    results, failures = [], []
    for index, source in enumerate(sources, 1):
        try:
            result = export_session(source, output, args.codex_home, not args.readable_only)
            results.append(result)
            print(f"[{index}/{len(sources)}] {result['title']}")
        except (OSError, ValueError, TypeError) as error:
            failures.append({"source": str(source), "error": str(error)})
            print(f"Failed: {source}: {error}", file=sys.stderr)
    manifest = {"sessions": results, "failures": failures}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    links = ['<li><a href="' + html.escape(Path(item['html']).as_posix(), quote=True) + '">'
             + html.escape(item['title']) + '</a></li>' for item in results]
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Codex archive</title>'
        '<h1>Codex archive</h1><ul>' + ''.join(links) + '</ul>', encoding="utf-8")
    print(f"Exported {len(results)} sessions; {len(failures)} failures. Index: {output / 'index.html'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
