"""Direct execution engine for parsed HMK expressions."""

from dataclasses import dataclass, field
from himark.node import HMKNode
from himark.utils.alphabet import ALPHABETS as _ALPHABETS
from himark.utils.alphabet import CASE_AGNOSTIC_ALPHABETS as _CASE_AGNOSTIC_ALPHABETS
from himark.utils.alphabet import alpha_value as _alpha_value
from himark.utils.alphabet import all_in_alphabet as _all_in_alphabet
from himark.utils.varied_rep import collect_var_specs, iter_bindings
from himark.utils import emoji as _emoji
from himark.utils import latex as _latex


@dataclass
class Match:
    text: str
    start: int
    end: int
    groups: list[str] = field(default_factory=list)
    group_spans: list[tuple[int, int]] = field(default_factory=list)  # (start, end) relative to match.start
    sub_groups: list[list[str]] = field(default_factory=list)  # sub_groups[i] = per-repetition texts for group i
    bindings: dict[str, int] = field(default_factory=dict)


class _SkipTo:
    """Sentinel: negation found its excluded content at the scan start; skip past it."""

    __slots__ = ("pos",)

    def __init__(self, pos: int) -> None:
        self.pos = pos


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute(steps: list[HMKNode], target: str) -> list[str]:
    """Execute an ordered list of HMK step trees against target.

    steps[0]      — pattern applied to target
    steps[1:-1]   — intermediate patterns, each applied to the previous step's matches
    steps[-1]     — template (when len > 1) rendered against the final matches
    """
    current: list[Match] = _find_matches(steps[0], target)

    if len(steps) == 1:
        return [m.text for m in current]

    for step_tree in steps[1:-1]:
        next_: list[Match] = []
        for m in current:
            next_.extend(_find_matches(step_tree, m.text))
        current = next_

    template_tree = steps[-1]
    return [_render(template_tree, m) for m in current]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _find_matches(tree: HMKNode, text: str) -> list[Match]:
    # Separator-only root: split mode
    if (
        tree.type == "root"
        and len(tree.children) == 1
        and tree.children[0].type == "double_chevrons"
    ):
        return _split_by_separator(tree.children[0], text)

    specs = collect_var_specs(tree)

    matches = []
    pos = 0
    while pos < len(text):
        remaining = len(text) - pos
        found = False
        for bindings in iter_bindings(specs, remaining):
            captures: list[str] = []
            capture_spans: list[tuple[int, int]] = []
            sub_capture_lists: list[list[str]] = []
            end = _match_node(tree, text, pos, captures, bindings, capture_spans, sub_capture_lists)
            if isinstance(end, _SkipTo):
                pos = end.pos
                found = True
                break
            if end is not None and end > pos:
                rel_spans = [(s - pos, e - pos) for s, e in capture_spans]
                matches.append(Match(text[pos:end], pos, end, captures, rel_spans, sub_capture_lists, bindings))
                pos = end
                found = True
                break
        if not found:
            pos += 1
    return matches


def _split_by_separator(node: HMKNode, text: str) -> list[Match]:
    if not node.children:
        return []
    sep = node.children[0].content
    parts = text.split(sep)
    matches, pos = [], 0
    for part in parts:
        matches.append(Match(part, pos, pos + len(part)))
        pos += len(part) + len(sep)
    return matches


def _match_node(
    node: HMKNode,
    text: str,
    pos: int,
    captures: list[str] | None = None,
    bindings: dict[str, int] | None = None,
    capture_spans: list[tuple[int, int]] | None = None,
    sub_capture_lists: list[list[str]] | None = None,
) -> int | _SkipTo | None:
    if node.type == "root":
        return _match_sequence(node.children, text, pos, captures, bindings, capture_spans, sub_capture_lists)
    if node.type == "single_brackets":
        return _match_bracket(node, text, pos, captures, bindings, capture_spans, sub_capture_lists)
    if node.type == "double_brackets":
        return _match_bracket_negated(node, text, pos)
    if node.type == "double_chevrons":
        # Sequence context: match the separator literal and advance past it
        if not node.children:
            return None
        s = node.children[0].content
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if node.type == "leaf":
        s = node.content
        if s == "^^":
            return pos if pos == 0 else None
        if s == "$$":
            return pos if pos == len(text) else None
        if s == "^":
            return pos if (pos == 0 or text[pos - 1] == "\n") else None
        if s == "$":
            return pos if (pos == len(text) or text[pos] == "\n") else None
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    return None


def _match_sequence(
    nodes: list[HMKNode],
    text: str,
    pos: int,
    captures: list[str] | None = None,
    bindings: dict[str, int] | None = None,
    capture_spans: list[tuple[int, int]] | None = None,
    sub_capture_lists: list[list[str]] | None = None,
) -> int | _SkipTo | None:
    current = pos
    for node in nodes:
        end = _match_node(node, text, current, captures, bindings, capture_spans, sub_capture_lists)
        if end is None:
            return None
        if isinstance(end, _SkipTo):
            return end  # propagate to _find_matches to skip past excluded content
        current = end
    return current


def _match_bracket(
    node: HMKNode,
    text: str,
    pos: int,
    captures: list[str] | None = None,
    bindings: dict[str, int] | None = None,
    capture_spans: list[tuple[int, int]] | None = None,
    sub_capture_lists: list[list[str]] | None = None,
) -> int | None:
    if not node.children:
        return None
    content = node.children[0]
    options = _flatten_options(node.metadata.get("options", []))
    min_count, max_count, lazy = _parse_repetition(options, bindings)

    ci = _parse_case_insensitive(options)
    alphabet = _parse_alphabet(options)
    pad = _parse_pad(options)
    start_pos = pos
    positions = [pos]
    current = pos
    count = 0
    while max_count is None or count < max_count:
        end = _match_content(content, text, current, ci, alphabet, pad)
        if end is None or end == current:
            break
        count += 1
        current = end
        positions.append(current)

    if count < min_count:
        return None
    result = positions[min_count] if lazy else positions[-1]
    if captures is not None:
        captures.append(text[start_pos:result])
    if capture_spans is not None:
        capture_spans.append((start_pos, result))
    if sub_capture_lists is not None:
        end_idx = min_count if lazy else len(positions) - 1
        subs = [text[positions[i]:positions[i + 1]] for i in range(end_idx)]
        sub_capture_lists.append(subs)
    return result


def _match_bracket_negated(node: HMKNode, text: str, pos: int) -> int | _SkipTo | None:
    if not node.children:
        return None
    content = node.children[0]
    start = pos
    while pos < len(text):
        inner_end = _match_content(content, text, pos)
        if inner_end is not None:
            break  # excluded content found — stop the run
        pos += 1
    if pos > start:
        return pos
    # Zero-length run: excluded content is right here — skip past it atomically
    inner_end = _match_content(content, text, start)
    if inner_end is not None and inner_end > start:
        return _SkipTo(inner_end)
    return _SkipTo(start + 1)


def _match_content(
    node: HMKNode,
    text: str,
    pos: int,
    ci: bool = False,
    alphabet: str | None = None,
    pad: int | None = None,
) -> int | None:
    if pos >= len(text):
        return None
    if node.type == "literal":
        s = node.content
        if ci:
            return (
                pos + len(s) if text[pos : pos + len(s)].lower() == s.lower() else None
            )
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if node.type == "shortcut":
        return _match_shortcut(node.metadata["kind"], text, pos)
    if node.type == "range":
        return _match_range(
            node.metadata["start"], node.metadata["end"], text, pos, ci, alphabet, pad
        )
    if node.type == "alternation":
        for arm in node.children:
            end = _match_content(arm, text, pos, ci, alphabet, pad)
            if end is not None:
                return end
        return None
    return None


_SHORTCUT_PREDS = {
    "digits": lambda c: c.isdigit(),
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


def _match_range(
    start: str,
    end: str,
    text: str,
    pos: int,
    ci: bool = False,
    alphabet: str | None = None,
    pad: int | None = None,
) -> int | None:
    if not start or not end:
        return None
    if alphabet is not None and alphabet not in ("b10", "dec"):
        alpha = _ALPHABETS[alphabet]
        case_agnostic = alphabet in _CASE_AGNOSTIC_ALPHABETS
        return _match_alphabet_range(start, end, alpha, case_agnostic, text, pos, pad)
    # Decimal / default
    if start.isdigit() and end.isdigit():
        return _match_integer_range(int(start), int(end), text, pos, pad)
    ch = text[pos]
    # cross-case shorthand: [a..Z] = a-z | A-Z, [b..A] = b-z | A-Z
    # The uppercase endpoint signals cross-case; the full A-Z range is always included.
    if start.islower() and end.isupper():
        return pos + 1 if (start <= ch <= "z" or "A" <= ch <= "Z") else None
    if ci:
        return pos + 1 if start.lower() <= ch.lower() <= end.lower() else None
    return pos + 1 if start <= ch <= end else None


def _match_integer_range(
    lo: int, hi: int, text: str, pos: int, pad: int | None = None
) -> int | None:
    if pad is not None:
        candidate = text[pos : pos + pad]
        if len(candidate) != pad or not candidate.isdigit():
            return None
        return (pos + pad) if lo <= int(candidate) <= hi else None
    end = pos
    while end < len(text) and text[end].isdigit():
        end += 1
    if end == pos:
        return None
    for length in range(end - pos, 0, -1):
        candidate = text[pos : pos + length]
        if length > 1 and candidate[0] == "0":
            continue  # no leading zeros
        if lo <= int(candidate) <= hi:
            return pos + length
    return None


def _match_alphabet_range(
    start: str,
    end: str,
    alpha: str,
    case_agnostic: bool,
    text: str,
    pos: int,
    pad: int | None,
) -> int | None:
    if case_agnostic:
        start, end = start.lower(), end.lower()
    if not start or not end:
        return None
    # Endpoints may be multi-character values (e.g. 0..ff in hex).
    if not _all_in_alphabet(start, alpha) or not _all_in_alphabet(end, alpha):
        return None
    lo, hi = _alpha_value(start, alpha), _alpha_value(end, alpha)
    zero = alpha[0]

    if pad is not None:
        candidate = text[pos : pos + pad]
        if len(candidate) != pad:
            return None
        if case_agnostic:
            candidate = candidate.lower()
        if not all(c in alpha for c in candidate):
            return None
        return (pos + pad) if lo <= _alpha_value(candidate, alpha) <= hi else None

    # Collect alphabet chars greedily
    end_pos = pos
    while end_pos < len(text):
        ch = text[end_pos].lower() if case_agnostic else text[end_pos]
        if ch not in alpha:
            break
        end_pos += 1
    if end_pos == pos:
        return None
    # Try longest first; skip leading "zeros" (index-0 char) for canonical form
    for length in range(end_pos - pos, 0, -1):
        candidate = text[pos : pos + length]
        if case_agnostic:
            candidate = candidate.lower()
        if length > 1 and candidate[0] == zero:
            continue
        if lo <= _alpha_value(candidate, alpha) <= hi:
            return pos + length
    return None


# ---------------------------------------------------------------------------
# Option parsing helpers
# ---------------------------------------------------------------------------

_IGNORED_OPTIONS: frozenset[str] = (
    frozenset()
)  # all formerly-ignored options are now handled


def _flatten_options(options: list[HMKNode]) -> list[HMKNode]:
    result = []
    for opt in options:
        if opt.type == "option_list":
            result.extend(_flatten_options(opt.children))
        else:
            result.append(opt)
    return result


def _parse_case_insensitive(options: list[HMKNode]) -> bool:
    return any(opt.type == "option" and opt.content == "i" for opt in options)


def _parse_alphabet(options: list[HMKNode]) -> str | None:
    for opt in options:
        if opt.type == "option" and opt.content in _ALPHABETS:
            return opt.content
    return None


def _parse_pad(options: list[HMKNode]) -> int | None:
    for opt in options:
        if opt.type == "pad":
            w = opt.metadata.get("width", "")
            return int(w) if w.isdigit() else None
    return None


def _is_var(s: str) -> bool:
    return len(s) == 1 and s.isalpha()


def _resolve(s: str, bindings: dict[str, int] | None) -> int | None:
    """Return int if s is a digit string or a bound variable; else None."""
    if s.isdigit():
        return int(s)
    if bindings and _is_var(s) and s in bindings:
        return bindings[s]
    return None


def _parse_repetition(
    options: list[HMKNode],
    bindings: dict[str, int] | None = None,
) -> tuple[int, int | None, bool]:
    min_count, max_count, lazy = 1, 1, False
    for opt in options:
        if opt.type == "repetition_range":
            mn, mx = opt.metadata["min"], opt.metadata["max"]
            resolved_mn = _resolve(mn, bindings) if mn else None
            resolved_mx = _resolve(mx, bindings) if mx else None
            min_count = resolved_mn if resolved_mn is not None else (0 if not mn else min_count)
            max_count = resolved_mx  # None means unbounded
        elif opt.type == "option":
            if opt.content.isdigit():
                min_count = max_count = int(opt.content)
            elif opt.content in _ALPHABETS or opt.content == "i":
                pass  # handled by _parse_alphabet / _parse_case_insensitive
            elif _is_var(opt.content) and bindings and opt.content in bindings:
                min_count = max_count = bindings[opt.content]
            else:
                pass  # unresolved variable — collect_var_specs handles enumeration
        elif opt.type == "lazy":
            lazy = True
        # pad is handled by _parse_pad; does not affect repetition counts
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
                path = expr.metadata["index"]
                g_idx = path[0] - 1
                if len(path) == 1:
                    parts.append(match.groups[g_idx] if g_idx < len(match.groups) else "")
                else:
                    s_idx = path[1] - 1
                    subs = match.sub_groups[g_idx] if g_idx < len(match.sub_groups) else []
                    parts.append(subs[s_idx] if s_idx < len(subs) else "")
            elif expr.type == "span_ref":
                s_idx = expr.metadata["start"][0] - 1  # top-level group index (0-based)
                e_idx = expr.metadata["end"][0] - 1
                if s_idx < len(match.group_spans) and e_idx < len(match.group_spans):
                    s = match.group_spans[s_idx][0]
                    e = match.group_spans[e_idx][1]
                    parts.append(match.text[s:e])
                else:
                    parts.append("")
            elif expr.type == "var_ref":
                val = match.bindings.get(expr.content)
                parts.append(str(val) if val is not None else "")
            elif expr.type == "emoji":
                parts.append(_emoji.resolve(expr.metadata["code"]))
            elif expr.type == "latex":
                parts.append(_latex.resolve(expr.metadata["expr"]))
    return "".join(parts)
