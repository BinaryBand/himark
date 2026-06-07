"""Direct execution engine for parsed HMK expressions."""

from dataclasses import dataclass, field
from himark.node import HMKNode


@dataclass
class Match:
    text: str
    start: int
    end: int
    groups: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute(
    pattern_tree: HMKNode,
    target: str,
    template_tree: HMKNode | None = None,
) -> list[str]:
    matches = _find_matches(pattern_tree, target)
    if template_tree is None:
        return [m.text for m in matches]
    return [_render(template_tree, m) for m in matches]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _find_matches(tree: HMKNode, text: str) -> list[Match]:
    matches = []
    pos = 0
    while pos < len(text):
        end = _match_node(tree, text, pos)
        if end is not None and end > pos:
            matches.append(Match(text[pos:end], pos, end))
            pos = end
        else:
            pos += 1
    return matches


def _match_node(node: HMKNode, text: str, pos: int) -> int | None:
    if node.type == "root":
        return _match_sequence(node.children, text, pos)
    if node.type == "single_brackets":
        return _match_bracket(node, text, pos)
    if node.type == "double_brackets":
        raise NotImplementedError("Negation [[...]] not yet supported")
    if node.type == "double_chevrons":
        raise NotImplementedError("Separators <<...>> not yet supported")
    if node.type == "leaf":
        s = node.content
        return pos + len(s) if text[pos:pos + len(s)] == s else None
    return None


def _match_sequence(nodes: list[HMKNode], text: str, pos: int) -> int | None:
    current = pos
    for node in nodes:
        end = _match_node(node, text, current)
        if end is None:
            return None
        current = end
    return current


def _match_bracket(node: HMKNode, text: str, pos: int) -> int | None:
    if not node.children:
        return None
    content = node.children[0]
    options = _flatten_options(node.metadata.get("options", []))
    min_count, max_count, lazy = _parse_repetition(options)

    positions = [pos]
    current = pos
    count = 0
    while max_count is None or count < max_count:
        end = _match_content(content, text, current)
        if end is None or end == current:
            break
        count += 1
        current = end
        positions.append(current)

    if count < min_count:
        return None
    return positions[min_count] if lazy else positions[-1]


def _match_content(node: HMKNode, text: str, pos: int) -> int | None:
    if pos >= len(text):
        return None
    if node.type == "literal":
        s = node.content
        return pos + len(s) if text[pos:pos + len(s)] == s else None
    if node.type == "shortcut":
        return _match_shortcut(node.metadata["kind"], text, pos)
    if node.type == "range":
        return _match_range(node.metadata["start"], node.metadata["end"], text, pos)
    if node.type == "alternation":
        for arm in node.children:
            end = _match_content(arm, text, pos)
            if end is not None:
                return end
        return None
    return None


_SHORTCUT_PREDS = {
    "digits":     lambda c: c.isdigit(),
    "word_chars": lambda c: c.isalnum() or c == "_",
    "whitespace": str.isspace,
}


def _match_shortcut(kind: str, text: str, pos: int) -> int | None:
    if kind == "any_char":
        return pos + 1
    pred = _SHORTCUT_PREDS[kind]
    if not pred(text[pos]):
        return None
    end = pos + 1
    while end < len(text) and pred(text[end]):
        end += 1
    return end


def _match_range(start: str, end: str, text: str, pos: int) -> int | None:
    if not start or not end:
        return None
    ch = text[pos]
    # cross-case shorthand: [a..Z] = a-z | A-Z
    if start.islower() and end.isupper():
        return pos + 1 if (start <= ch <= "z" or "A" <= ch <= end) else None
    return pos + 1 if start <= ch <= end else None


# ---------------------------------------------------------------------------
# Option parsing helpers
# ---------------------------------------------------------------------------

_IGNORED_OPTIONS = {"hex", "b10", "dec", "b16", "b32", "b58", "b64", "i"}


def _flatten_options(options: list[HMKNode]) -> list[HMKNode]:
    result = []
    for opt in options:
        if opt.type == "option_list":
            result.extend(_flatten_options(opt.children))
        else:
            result.append(opt)
    return result


def _parse_repetition(options: list[HMKNode]) -> tuple[int, int | None, bool]:
    min_count, max_count, lazy = 1, 1, False
    for opt in options:
        if opt.type == "repetition_range":
            mn, mx = opt.metadata["min"], opt.metadata["max"]
            min_count = int(mn) if mn else 0
            max_count = int(mx) if mx else None
        elif opt.type == "option":
            if opt.content.isdigit():
                min_count = max_count = int(opt.content)
            elif opt.content not in _IGNORED_OPTIONS:
                raise NotImplementedError(f"Varied repetition variable '{opt.content}' not yet supported")
        elif opt.type == "lazy":
            lazy = True
        # pad and alphabet modifiers are silently ignored by the matcher
    return min_count, max_count, lazy


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _render(template_tree: HMKNode, match: Match) -> str:
    parts = []
    for node in template_tree.children:
        if node.type == "leaf":
            parts.append(node.content)
        elif node.type == "double_braces" and node.children:
            expr = node.children[0]
            if expr.type == "full_match":
                parts.append(match.text)
            elif expr.type == "group_ref":
                idx = expr.metadata["index"][0] - 1
                parts.append(match.groups[idx] if idx < len(match.groups) else "")
            elif expr.type == "var_ref":
                raise NotImplementedError(f"Varied repetition var '{{{{ {expr.content} }}}}' not yet supported")
    return "".join(parts)
