#!/usr/bin/env python3
"""Mirror docs/ to docs-zh/ with Chinese translation via deep-translator (free, no API key).

Adapted from the crud-skeleton project. Differences for AssemblyVision:

- All content is translated, including `research/` (external reference material with
  heavy URL content — URLs and links are preserved while surrounding text is translated).
- Mermaid diagrams ARE translated: node labels, edge text, subgraph titles, sequence
  participants/messages/notes, and state/ER transition labels are translated while
  the diagram syntax (arrows, brackets, identifiers, keywords) is preserved.
- Headings are translated but keep their original English slug as an explicit
  `{#slug}` attribute (requires the `attr_list` Markdown extension). This keeps
  cross-document anchor links such as `appendices.md#3-global-open-questions`
  working in the Chinese build, because Material honors explicit heading ids.

Known limitation: `deep-translator` uses Google's free translation endpoint. It has
no hard character guarantee and may be rate-limited. On any failure the script keeps
the original (English) chunk so the build never breaks. Machine translation is a
starting point and should be reviewed for accuracy.

Usage:
    pip install deep-translator
    python scripts/translate-docs.py
    python scripts/translate-docs.py design/appendices.md   # single file
"""

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs"
DST = ROOT / "docs-zh"

SKIP_DIRS = {}

STASH: list[str] = []
HEADINGS: list[tuple[str, str]] = []  # (level prefix, raw heading text)


def stash(text: str, pattern: str) -> str:
    """Replace matches of `pattern` with <tN/> placeholders for later restore."""

    def _stash(m: re.Match) -> str:
        idx = len(STASH)
        STASH.append(m.group(0))
        return f"<t{idx}/>"

    return re.sub(pattern, _stash, text)


def slugify(text: str) -> str:
    """Approximate the Markdown/Material heading slug for English text.

    Keeps unicode word characters so Chinese headings also get stable ids, but the
    injected id always comes from the original English heading.
    """
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def stash_headings(body: str) -> str:
    """Replace heading lines with <hN/> placeholders, recording level and text."""

    def _stash(m: re.Match) -> str:
        idx = len(HEADINGS)
        HEADINGS.append((m.group(1), m.group(2)))
        return f"<h{idx}/>"

    return re.sub(r"(?m)^(#{1,6})\s+(.+?)\s*$", _stash, body)


def translate_heading(text: str, translator) -> str:
    """Translate a heading, keeping inline code untouched and stable id."""
    inline: list[str] = []

    def _rep(m: re.Match) -> str:
        idx = len(inline)
        inline.append(m.group(0))
        return f"<hi{idx}/>"

    guarded = re.sub(r"`[^`]+`", _rep, text)
    try:
        zh = translator.translate(guarded)
    except Exception:
        zh = guarded
    for i, block in enumerate(inline):
        for variant in (f"<hi{i}/>", f"<hi{i} />", f"<hi {i}/>", f"<hi {i} />"):
            zh = zh.replace(variant, block)
    return zh


def restore(body: str) -> str:
    for i, block in enumerate(STASH):
        for variant in (f"<t{i}/>", f"<t{i} />", f"<t{i}>", f"<t {i}/>", f"<t {i} />", f"<t {i}>"):
            body = body.replace(variant, block)
    return body


# ---------------------------------------------------------------------------
# Mermaid translation
# ---------------------------------------------------------------------------
# Translate the human-readable labels inside Mermaid diagrams while preserving
# the diagram syntax (flowchart/graph/sequence/state/ER keywords, arrows,
# brackets, node identifiers, and participant names stay untouched).


def _tr(text: str, translator) -> str:
    text = (text or "").strip()
    if not text:
        return text
    try:
        return translator.translate(text).strip()
    except Exception:
        return text


def _translate_segments(line: str, translator) -> str:
    """Translate label content in a single data line (nodes, edges, state/ER text)."""
    # Dashed/dotted edge labels:  A -. text .-> B | A -- text --> B | A == text ==> B
    line = re.sub(r"(-\.[ \t]+)([^.\n]+?)([ \t]+\.->)", lambda m: m.group(1) + _tr(m.group(2), translator) + m.group(3), line)
    line = re.sub(r"(--[ \t]+)([^>\n]+?)([ \t]+-->)", lambda m: m.group(1) + _tr(m.group(2), translator) + m.group(3), line)
    line = re.sub(r"(==[ \t]+)([^>\n]+?)([ \t]+==>)", lambda m: m.group(1) + _tr(m.group(2), translator) + m.group(3), line)
    pattern = re.compile(
        r"\[\[(?P<sub>[^\]\n]*)\]\]"        # subroutine  [[label]]
        r"|\[\((?P<cyl>[^\]\n]*)\)\]"       # cylinder    [(label)]
        r"|\(\((?P<circ>[^()\n]*)\)\)"      # circle      ((label))
        r"|\{(?P<rh>[^}\n]*)\}"             # rhombus     {label}
        r"|\|(?P<edge>[^|\n]*)\|"           # edge label  -->|label|
        r"|\[(?P<node>[^\]\n]*)\]"          # rectangle   [label]
        r"|(?P<colon>:)[^:\n\]}|]*$"        # state/seq/ER text after ': '
    )
    delims = {
        "sub": ("[[", "]]"),
        "cyl": ("[(", ")]"),
        "circ": ("((", "))"),
        "rh": ("{", "}"),
        "edge": ("|", "|"),
        "node": ("[", "]"),
    }

    def _repl(m: re.Match) -> str:
        d = m.groupdict()
        for name, (op, cl) in delims.items():
            if d[name] is not None:
                return op + _tr(d[name], translator) + cl
        if d["colon"] is not None:
            return ":" + _tr(m.group(0)[1:], translator)
        return m.group(0)

    return pattern.sub(_repl, line)


def _translate_alias_line(line: str, translator) -> str:
    m = re.match(r"^(\s*(?:participant|actor)\s+\S+)(\s+as\s+)(.+)$", line)
    if m:
        return m.group(1) + m.group(2) + _tr(m.group(3), translator)
    return line


def _translate_note_line(line: str, translator) -> str:
    m = re.match(r"^(\s*[Nn]ote\b[^:]*:)(.*)$", line)
    if m:
        return m.group(1) + _tr(m.group(2), translator)
    return line


def _translate_subgraph_line(line: str, translator) -> str:
    m = re.match(r"^(\s*subgraph\s+\S+)(\[[^\]]*\])", line)
    if m:
        return m.group(1) + "[" + _tr(m.group(2)[1:-1], translator) + "]"
    m2 = re.match(r"^(\s*subgraph\s+)(.+)$", line)
    if m2:
        return m2.group(1) + _tr(m2.group(2), translator)
    return line


def _translate_block_label(line: str, translator) -> str:
    parts = line.split(None, 1)
    if len(parts) == 2 and parts[1]:
        return parts[0] + " " + _tr(parts[1], translator)
    return line


def translate_mermaid(src: str, translator) -> str:
    """Translate labels/edge text inside a Mermaid diagram, keeping syntax."""
    out: list[str] = []
    for raw in src.split("\n"):
        low = raw.strip().lower()
        if (low.startswith(("flowchart", "graph", "sequence", "state", "class",
                            "er", "mindmap", "journey", "pie", "gantt", "timeline",
                            "quadrantchart", "xychart", "block", "sankey", "gitgraph",
                            "zenuml"))
                or low in ("end", "autonumber")):
            out.append(raw)
            continue
        if low.startswith(("participant ", "actor ")):
            out.append(_translate_alias_line(raw, translator))
            continue
        if low.startswith("note "):
            out.append(_translate_note_line(raw, translator))
            continue
        if low.startswith("subgraph"):
            out.append(_translate_subgraph_line(raw, translator))
            continue
        if low.startswith(("alt ", "else ", "opt ", "loop ", "par ", "rect ", "and ")):
            out.append(_translate_block_label(raw, translator))
            continue
        out.append(_translate_segments(raw, translator))
    return "\n".join(out)


def stash_fenced(body: str, translator) -> str:
    """Stash fenced code blocks; Mermaid blocks are translated first.

    Translated Mermaid content is placed back in STASH as a single opaque block
    so the generic paragraph translation below never re-translates it.
    """

    def _repl(m: re.Match) -> str:
        fence_open, content, fence_close = m.groups()
        lang = fence_open.strip().strip("`").strip()
        if lang.lower() == "mermaid":
            translated = translate_mermaid(content, translator)
            idx = len(STASH)
            STASH.append(f"{fence_open}{translated}{fence_close}")
            return f"<t{idx}/>"
        idx = len(STASH)
        STASH.append(m.group(0))
        return f"<t{idx}/>"

    return re.sub(r"(```[^\n]*\n)([\s\S]*?)(```)", _repl, body)


def translate_file(src_path: Path, dst_path: Path, translator) -> None:
    global STASH, HEADINGS
    STASH = []
    HEADINGS = []

    content = src_path.read_text(encoding="utf-8").strip()
    if not content:
        return

    frontmatter = ""
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[: end + 3] + "\n\n"
            body = content[end + 3:].strip()

    if not body:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text(frontmatter + "\n", encoding="utf-8")
        return

    # Stash non-translatable blocks (most specific first). Mermaid blocks are
    # translated in place (labels/edge text) before being stashed as a whole.
    body = stash_fenced(body, translator)   # fenced code blocks (Mermaid-aware)
    body = stash_headings(body)             # heading lines (translated separately)
    body = stash(body, r"`[^`]+`")               # inline code
    body = stash(body, r"<!--[\s\S]*?-->")       # HTML comments
    body = stash(body, r"!\[.*?\]\(.*?\)")       # images
    body = stash(body, r"\[([^\]]*)\]\(([^\)]+)\)")  # links [text](url)

    # Split into paragraphs and translate in chunks (free Google limit ~5k chars;
    # keep chunks comfortably below it). Oversized single paragraphs, such as a
    # large markdown table, are hard-split on line boundaries so every chunk fits.
    max_chars = 4000
    blocks = body.split("\n\n")
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for block in blocks:
        if len(block) <= max_chars:
            if len(current) + len(block) + 2 <= max_chars:
                current = (current + "\n\n" + block) if current else block
            else:
                flush()
                current = block
        else:
            flush()
            for line in block.split("\n"):
                if len(current) + len(line) + 1 <= max_chars:
                    current = (current + "\n" + line) if current else line
                else:
                    flush()
                    current = line
    flush()

    translated_chunks = []
    for i, chunk in enumerate(chunks):
        try:
            tc = translator.translate(chunk)
        except Exception as e:
            print(f"  WARN chunk {i}: {e}, keeping original")
            tc = chunk
        translated_chunks.append(tc)

    body_zh = "\n\n".join(translated_chunks)

    # Restore headings with translated text and a stable English anchor id.
    for i, (level, raw_text) in enumerate(HEADINGS):
        zh_text = translate_heading(raw_text, translator)
        anchor = slugify(raw_text)
        rendered = f"{level} {zh_text} {{#{anchor}}}"
        for variant in (f"<h{i}/>", f"<h{i} />", f"<h {i}/>", f"<h {i} />"):
            body_zh = body_zh.replace(variant, rendered)

    body_zh = restore(body_zh)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(frontmatter + body_zh + "\n", encoding="utf-8")


def main():
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        print("ERROR: pip install deep-translator")
        sys.exit(1)

    translator = GoogleTranslator(source="en", target="zh-CN")

    if len(sys.argv) > 1:
        rel = sys.argv[1]
        translate_file(SRC / rel, DST / rel, translator)
        print(f"Done -> {DST / rel}")
        return

    files = sorted(SRC.rglob("*.md"))
    total = 0

    for src_path in files:
        rel = src_path.relative_to(SRC)
        if any(d in rel.parts for d in SKIP_DIRS):
            continue
        total += 1
        print(f"[{total}] {rel}", end=" ", flush=True)
        translate_file(src_path, DST / rel, translator)
        print("OK")

    print(f"\nDone. {total} files mirrored to {DST}/")


if __name__ == "__main__":
    main()
