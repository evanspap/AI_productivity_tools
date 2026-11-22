#!/usr/bin/env python3
"""Archive local Codex sessions, including all recorded events, without APIs."""
import argparse
from collections import Counter
import html
import hashlib
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


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_inventory(output, result, markdown_only):
    directory = output / result['directory']
    paths = [output / result['markdown']]
    paths.extend(p for p in (directory / 'assets').rglob('*') if p.is_file())
    if not markdown_only:
        paths.extend([output / result['html'], directory / 'original.jsonl', directory / 'metadata.json'])
    return {str(p.relative_to(output)): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}


def outputs_present(output, inventory):
    if not inventory:
        return False
    for relative, stamp in inventory.items():
        path = output / relative
        if not path.is_file() or [path.stat().st_size, path.stat().st_mtime_ns] != stamp:
            return False
    return True


def readable_items(records, directory, full):
    """Render conversation, commentary and recorded reasoning without tool traffic."""
    items = []
    for number, record in enumerate(records):
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        image_folder = directory / "assets" / str(number)
        visible = chat.extract_messages([record], image_folder, True)
        if visible:
            for item in visible:
                item["parts"] = [(kind, value.replace("assets/", f"assets/{number}/", 1)
                                  if kind == "image" else value) for kind, value in item["parts"]]
            items.extend(visible)
            continue
        if not full:
            continue
        subtype = payload.get("type", "")
        text, label = "", ""
        if record.get("type") == "response_item" and subtype == "reasoning":
            parts = (payload.get("summary") or []) + (payload.get("content") or [])
            text = "\n\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text"))
            label = "Recorded reasoning"
        elif record.get("type") == "event_msg" and subtype in ("agent_reasoning", "agent_reasoning_raw_content"):
            # Prefer structured reasoning items to their duplicate event stream.
            if any(r.get("type") == "response_item" and (r.get("payload") or {}).get("type") == "reasoning" for r in records):
                continue
            text = payload.get("text", "")
            label = "Recorded reasoning"
        if text:
            items.append({"role": "assistant", "phase": "commentary",
                          "timestamp": str(record.get("timestamp") or ""),
                          "parts": [("text", "**" + label + "**\n\n" + text)]})
    return items


def export_session(source, output, codex_home, full=True, markdown_only=False):
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
    header = next((r.get("payload", {}) for r in records if r.get("type") == "session_meta"), {})
    # Child logs share session_id with the parent but have their own thread id.
    meta["session_id"] = header.get("id") or meta["session_id"]
    sid = meta["session_id"]
    if not chat.UUID_RE.fullmatch(sid):
        raise ValueError(f"Missing valid session ID: {source}")
    title = chat.find_thread_name(sid, codex_home) or "codex-chat-" + sid
    meta["thread_name"] = title
    # Full UUID prevents collisions for identical or sanitized chat titles.
    directory = output / (chat.safe_filename(title, 85) + " -- " + sid)
    directory.mkdir(parents=True, exist_ok=True)
    if not markdown_only:
        (directory / "original.jsonl").write_bytes(snapshot)
    items = readable_items(records, directory, full)
    stem = chat.safe_filename(title, 100)
    md = directory / (stem + ".md")
    page = directory / (stem + ".html")
    md.write_text(chat.render_markdown(items, meta), encoding="utf-8")
    if not markdown_only:
        page.write_text(chat.render_html(items, meta), encoding="utf-8")
    counts = Counter(str(record.get("type", "unknown")) for record in records)
    result = {"session_id": sid, "title": title, "directory": directory.name,
              "source": str(source), "records": len(records), "event_types": dict(counts),
              "warnings": warnings, "html": str(page.relative_to(output)),
              "markdown": str(md.relative_to(output))}
    result['source_sha256'] = hashlib.sha256(snapshot).hexdigest()
    if not markdown_only:
        (directory / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--source-dir", type=Path, help="Search this local JSONL folder recursively instead")
    parser.add_argument("--session", help="Export only this UUID or Codex deeplink")
    parser.add_argument("--force", action="store_true", help="Rebuild even unchanged exports")
    parser.add_argument("--markdown-only", action="store_true", help="Write Markdown and image assets only; no HTML or JSON copies")
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
    state_path = output / '.export-state.json'
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    version = file_digest(Path(__file__)) + file_digest(Path(chat.__file__))
    mode = [args.markdown_only, args.readable_only]
    updated = skipped = 0
    results, failures = [], []
    for index, source in enumerate(sources, 1):
        try:
            key = str(source)
            previous = state.get(key, {})
            cached = previous.get('result', {})
            current_title = chat.find_thread_name(cached.get('session_id', ''), args.codex_home)
            if (not args.force and previous.get('version') == version
                    and previous.get('mode') == mode
                    and cached.get('source_sha256') == file_digest(source)
                    and (current_title or 'codex-chat-' + cached.get('session_id', '')) == cached.get('title')
                    and outputs_present(output, previous.get('outputs', {}))):
                results.append(cached)
                skipped += 1
                print(f"[{index}/{len(sources)}] SKIP: {cached['title']}")
                continue
            result = export_session(source, output, args.codex_home, not args.readable_only, args.markdown_only)
            results.append(result)
            updated += 1
            state[key] = {'version': version, 'mode': mode, 'result': result,
                          'outputs': output_inventory(output, result, args.markdown_only)}
            print(f"[{index}/{len(sources)}] {result['title']}")
        except (OSError, ValueError, TypeError) as error:
            failures.append({"source": str(source), "error": str(error)})
            print(f"Failed: {source}: {error}", file=sys.stderr)
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(state_path)
    # A single-session refresh must not erase the archive's existing index.
    if args.session:
        seen = {r['session_id'] for r in results}
        results.extend(entry['result'] for entry in state.values()
                       if entry.get('mode') == mode and entry.get('result', {}).get('session_id') not in seen
                       and (output / entry['result']['markdown']).is_file())
    print(f"Updated: {updated}; unchanged: {skipped}; failures: {len(failures)}")
    manifest = {"sessions": results, "failures": failures}
    if args.markdown_only:
        from urllib.parse import quote
        lines = ["# Codex archive", ""]
        for item in results:
            target = quote(Path(item["markdown"]).as_posix())
            lines.append("- [" + item["title"].replace("[", "\\[").replace("]", "\\]") + "](" + target + ")")
            lines.extend("  - Warning: " + warning.replace("; retained in original.jsonl", "") for warning in item["warnings"])
        for failure in failures:
            lines.append("- FAILED: " + failure["source"] + ": " + failure["error"])
        (output / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Exported {len(results)} sessions; {len(failures)} failures. Index: {output / 'index.md'}")
        return 1 if failures else 0
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    links = ['<li><a href="' + html.escape(Path(item['html']).as_posix(), quote=True) + '">'
             + html.escape(item['title']) + '</a></li>' for item in results]
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Codex archive</title>'
        '<h1>Codex archive</h1><ul>' + ''.join(links) + '</ul>', encoding="utf-8")
    print(f"Exported {len(results)} sessions; {len(failures)} failures. Index: {output / 'index.html'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
