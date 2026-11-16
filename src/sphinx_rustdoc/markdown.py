"""Turn rustdoc's Markdown into MyST that renders the same way inside an item's description."""

from __future__ import annotations

import re

from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

# Placeholder link destinations, which the directive swaps for real links: an intra-doc link to an
# item, and a link to a heading in the same doc comment.
LINK_SCHEME = "rustdoc-item:"
ANCHOR_SCHEME = "rustdoc-anchor:"

FENCE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[(?P<label>[^\]]+)\]:\s*(?P<dest>\S+)\s*$")
# a URL scheme, but not the `::` of a Rust path such as `crate::Client`
URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!:)|^#|^/")
# rustdoc's warning block, which shows as a warning box:
# https://doc.rust-lang.org/rustdoc/how-to-write-documentation.html#adding-a-warning-block
WARNING = re.compile(r"""^ {0,3}<div\s+class\s*=\s*(["'])warning\1\s*>""")
DIV = re.compile(r"<div[\s>]|</div\s*>")
# a blockquote line, and its text after the `>`
QUOTE = re.compile(r"^ {0,3}> ?(?P<text>.*)$")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])(?:\s|$)")

# Code block attributes rustdoc reads as "this is Rust"
RUST_ATTRIBUTES = frozenset(
    {
        "rust",
        "ignore",
        "should_panic",
        "no_run",
        "compile_fail",
        "test_harness",
        "standalone_crate",
        "allow_fail",
    }
)


def _is_rust_attribute(token: str) -> bool:
    return (
        token in RUST_ATTRIBUTES
        or token.startswith(("edition", "ignore-", "{"))
        # the error code a compile_fail example expects, such as E0277
        or re.fullmatch(r"E[0-9]{4}", token) is not None
    )


def code_language(info: str) -> str:
    """The language of a fenced block, as rustdoc reads its info string.

    A language Pygments doesn't know is `text`, since rustdoc shows it as plain code and Sphinx
    would warn.
    """
    tokens = [t for t in re.split(r"[\s,]+", info.strip()) if t]
    for token in tokens:
        if not _is_rust_attribute(token):
            return token if _highlightable(token) else "text"
    return "rust"


def _highlightable(language: str) -> bool:
    try:
        get_lexer_by_name(language)
    except ClassNotFound:
        return False
    return True


def _hidden(line: str) -> bool:
    stripped = line.lstrip()
    return stripped == "#" or stripped.startswith("# ")


def _unescape_hash(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("##"):
        return line[: len(line) - len(stripped)] + stripped[1:]
    return line


def prepare(docs: str | None, links: dict[str, int]) -> str:
    """MyST for a doc comment: headings as rubrics, rustdoc's code and warning blocks, and link placeholders."""
    if not docs:
        return ""
    lines = docs.splitlines()
    return "\n".join(_prepare(lines, links, _definitions(lines)))


def _prepare(lines: list[str], links: dict[str, int], definitions: dict[str, str]) -> list[str]:
    out: list[str] = []
    # the current paragraph's lines, rewritten together, since a link's text can wrap onto the next line
    paragraph: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            out.append(_links("\n".join(paragraph), links, definitions))
            paragraph.clear()

    fence: str | None = None
    rust = False
    # whether the lines so far are in a list, whose indented paragraphs aren't code
    in_list = False
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if fence is not None:
            if _closes(line, fence):
                fence = None
                out.append(line)
            elif rust and _hidden(line):
                continue
            else:
                out.append(_unescape_hash(line) if rust else line)
            continue
        if LIST_ITEM.match(line):
            in_list = True
        elif line.strip() and not line[0].isspace():
            in_list = False
        if not paragraph and not in_list and line.strip() and _indent(line) >= 4:
            # an indented code block, which rustdoc reads as Rust; it can't interrupt a paragraph
            end = start = i - 1
            for j in range(start, len(lines)):
                if lines[j].strip() and _indent(lines[j]) < 4:
                    break
                if lines[j].strip():
                    end = j + 1
            body = [_unescape_hash(c) for c in (c.expandtabs(4)[4:] for c in lines[start:end]) if not _hidden(c)]
            outer = "`" * max(3, _longest_backtick_fence("\n".join(body)) + 1)
            out += [f"{outer}rust", *body, outer]
            i = end
            continue
        if QUOTE.match(line):
            end_paragraph()
            # the blockquote's lines without their `>`, prepared like the rest, then quoted again
            start = i - 1
            while i < len(lines) and QUOTE.match(lines[i]):
                i += 1
            inner = "\n".join(_prepare([QUOTE.match(q)["text"] for q in lines[start:i]], links, definitions))
            out += [f"> {q}" if q else ">" for q in inner.split("\n")]
            continue
        match = FENCE.match(line)
        if match:
            end_paragraph()
            fence = match["fence"]
            language = code_language(match["info"])
            rust = language == "rust"
            out.append(f"{match['indent']}{fence}{language}")
            continue
        warning = WARNING.match(line)
        block = _warning_block(lines, i - 1, warning.end()) if warning else None
        if block:
            end_paragraph()
            body, i, after = block
            if after.strip():
                lines = [*lines[:i], after, *lines[i:]]
            inner = "\n".join(_prepare(body, links, definitions))
            # longer than any code fence inside it, so theirs don't close it
            outer = "`" * max(3, _longest_backtick_fence(inner) + 1)
            out += ["", f"{outer}{{warning}}", inner, outer, ""]
            continue
        definition = REFERENCE_DEFINITION.match(line)
        if definition and (definition["dest"] in links or _intra_doc(definition["dest"])):
            end_paragraph()
            continue
        heading = HEADING.match(line)
        if heading:
            end_paragraph()
            # a tilde fence, since a heading can hold inline code and a backtick fence's info string can't
            out += ["", f"~~~{{rubric}} {_links(heading[2], links, definitions)}", "~~~", ""]
            continue
        if not line.strip():
            end_paragraph()
            out.append(line)
            continue
        paragraph.append(line)
    end_paragraph()
    return out


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip(" "))


def _closes(line: str, fence: str) -> bool:
    """Whether a line closes a code block that opened with `fence`."""
    stripped = line.strip()
    return stripped.startswith(fence[0]) and set(stripped) == {fence[0]} and len(stripped) >= len(fence)


def _warning_block(lines: list[str], start: int, offset: int) -> tuple[list[str], int, str] | None:
    """The lines inside the warning block that opens at `lines[start][offset:]`.

    Returns them with the index of the line after the block and the text after its `</div>`, or
    `None` if the block isn't closed. Divs nest, and code blocks inside it are skipped.
    """
    body: list[str] = []
    depth = 1
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index][offset:] if index == start else lines[index]
        if fence is not None:
            if _closes(line, fence):
                fence = None
            body.append(line)
            continue
        match = FENCE.match(line)
        if match and index != start:
            fence = match["fence"]
            body.append(line)
            continue
        for tag in DIV.finditer(line):
            depth += -1 if tag[0].startswith("</") else 1
            if depth == 0:
                body.append(line[: tag.start()])
                return body, index + 1, line[tag.end() :]
        body.append(line)
    return None


def _longest_backtick_fence(text: str) -> int:
    fences = (FENCE.match(line) for line in text.splitlines())
    return max((len(m["fence"]) for m in fences if m and m["fence"][0] == "`"), default=0)


def heading_id(text: str) -> str:
    """The id rustdoc gives a heading in a doc comment, which its own links use."""
    words = re.sub(r"[^\w\s-]", "", text.lower()).split()
    return "-".join(words)


def summary(docs: str | None, links: dict[str, int]) -> str:
    """The doc comment's first paragraph, as rustdoc shows it in a module's item list."""
    if not docs:
        return ""
    lines = docs.splitlines()
    paragraph: list[str] = []
    for line in lines:
        if not line.strip():
            if paragraph:
                break
            continue
        if FENCE.match(line) or HEADING.match(line):
            break
        paragraph.append(line.strip())
    # reference definitions usually follow the paragraph, at the end of the doc comment
    return _links(" ".join(paragraph), links, _definitions(lines))


def _definitions(lines: list[str]) -> dict[str, str]:
    """Each reference definition's destination, by its lowercased label."""
    definitions: dict[str, str] = {}
    for line in lines:
        match = REFERENCE_DEFINITION.match(line)
        if match:
            definitions[match["label"].lower()] = match["dest"]
    return definitions


def _links(text: str, links: dict[str, int], definitions: dict[str, str]) -> str:
    """Rewrite the intra-doc links in a paragraph to placeholder links rustdoc resolved."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if char == "`":
            run = len(text[i:]) - len(text[i:].lstrip("`"))
            end = text.find("`" * run, i + run)
            if end == -1:
                # backticks with no closing run are plain text, as in CommonMark
                out.append(text[i : i + run])
                i += run
                continue
            out.append(text[i : end + run])
            i = end + run
            continue
        if char != "[":
            out.append(char)
            i += 1
            continue
        close = _matching(text, i, "[", "]")
        if close is None:
            out.append(char)
            i += 1
            continue
        label = text[i + 1 : close]
        after = close + 1
        if after < n and text[after] == "(":
            end = _matching(text, after, "(", ")")
            if end is not None:
                dest = (text[after + 1 : end].split() or [""])[0]
                if dest in links:
                    out.append(f"[{label}]({LINK_SCHEME}{links[dest]})")
                elif dest.startswith("#"):
                    out.append(f"[{label}]({ANCHOR_SCHEME}{dest[1:]})")
                elif URL.match(dest):
                    out.append(text[i : end + 1])
                else:
                    # an intra-doc link rustdoc couldn't resolve: keep its text
                    out.append(label)
                i = end + 1
                continue
        if after < n and text[after] == "[":
            end = text.find("]", after)
            if end != -1:
                key = text[after + 1 : end] or label
                dest = definitions.get(key.lower())
                if dest is None and key in links:
                    # rustdoc resolves `[text][Item]` and `[Item][]` with no definition
                    out.append(f"[{label}]({LINK_SCHEME}{links[key]})")
                    i = end + 1
                    continue
                if dest is not None and dest in links:
                    out.append(f"[{label}]({LINK_SCHEME}{links[dest]})")
                    i = end + 1
                    continue
                if dest is not None and _intra_doc(dest):
                    # rustdoc couldn't resolve it: keep its text
                    out.append(label)
                    i = end + 1
                    continue
        dest = definitions.get(label.lower())
        if label in links:
            out.append(f"[{label}]({LINK_SCHEME}{links[label]})")
            i = after
            continue
        if dest is not None and dest in links:
            out.append(f"[{label}]({LINK_SCHEME}{links[dest]})")
            i = after
            continue
        if dest is not None and _intra_doc(dest):
            out.append(label)
            i = after
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _intra_doc(dest: str) -> bool:
    """Whether a link destination is an intra-doc link, resolved by rustdoc or not, rather than a URL."""
    return URL.match(dest) is None


def _matching(text: str, start: int, open_: str, close: str) -> int | None:
    depth = 0
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "`":
            run = len(text[i:]) - len(text[i:].lstrip("`"))
            end = text.find("`" * run, i + run)
            # backticks with no closing run are plain text
            i = i + run if end == -1 else end + run
            continue
        if char == open_:
            depth += 1
        elif char == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
