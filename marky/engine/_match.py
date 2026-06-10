from collections.abc import Callable

from marky.engine._types import Match, MatchCtx
from marky.models.node import HMKNode
from marky.utils.alphabet import ALPHABETS as _ALPHABETS
from marky.utils.alphabet import CASE_AGNOSTIC_ALPHABETS as _CASE_AGNOSTIC_ALPHABETS
from marky.utils.alphabet import all_in_alphabet as _all_in_alphabet
from marky.utils.alphabet import alpha_value as _alpha_value
from marky.utils.varied_rep import collect_var_specs, iter_bindings


class _SkipTo:
    """Sentinel: negation found its excluded content at the scan start; skip past it."""

    __slots__ = ("pos",)

    def __init__(self, pos: int) -> None:
        self.pos = pos


# ---------------------------------------------------------------------------
# Top-level match driver
# ---------------------------------------------------------------------------


def find_matches(tree: HMKNode, text: str) -> list[Match]:
    if (
        tree.type == "root"
        and len(tree.children) == 1
        and tree.children[0].type == "double_chevrons"
    ):
        node = tree.children[0]
        sep = node.children[0].content if node.children else ""
        if not sep:
            # <<>> alone: one match covering the entire text
            return [Match(text, 0, len(text))] if text else []
        return _split_by_separator(node, text)

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
            end = _match_node(
                tree, text, pos, captures, bindings, capture_spans, sub_capture_lists
            )
            if isinstance(end, _SkipTo):
                pos = end.pos
                found = True
                break
            if end is not None and end > pos:
                rel_spans = [(s - pos, e - pos) for s, e in capture_spans]
                matches.append(
                    Match(
                        text[pos:end],
                        pos,
                        end,
                        captures,
                        rel_spans,
                        sub_capture_lists,
                        bindings,
                    )
                )
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


# ---------------------------------------------------------------------------
# Node matching
# ---------------------------------------------------------------------------


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
        return _match_sequence(
            node.children,
            text,
            pos,
            captures,
            bindings,
            capture_spans,
            sub_capture_lists,
        )
    if node.type == "single_brackets":
        return _match_bracket(
            node, text, pos, captures, bindings, capture_spans, sub_capture_lists
        )
    if node.type == "double_brackets":
        return _match_bracket_negated(
            node, text, pos, captures, bindings, capture_spans, sub_capture_lists
        )
    if node.type == "double_chevrons":
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
    for i, node in enumerate(nodes):
        # Detect lazy wildcard: bare <<>> or [<<>>] without explicit count modifier.
        # Both act as "match minimum chars until the rest of the sequence can succeed"
        # and both create a capture group for what they consumed.
        is_chevron_wildcard = node.type == "double_chevrons" and not _chevron_sep(node)
        is_bracket_wildcard = (
            node.type == "single_brackets"
            and len(node.children) == 1
            and node.children[0].type == "double_chevrons"
            and not _chevron_sep(node.children[0])
            and not _has_explicit_count(
                _flatten_options(node.metadata.get("options", []))
            )
        )
        if is_chevron_wildcard or is_bracket_wildcard:
            remaining = nodes[i + 1 :]
            if not remaining:
                # Greedy terminal: consume everything left
                wc = text[current:]
                if captures is not None:
                    captures.append(wc)
                if capture_spans is not None:
                    capture_spans.append((current, len(text)))
                if sub_capture_lists is not None:
                    sub_capture_lists.append([wc])
                return len(text)
            for n in range(len(text) - current + 1):
                snap_c = len(captures) if captures is not None else 0
                snap_s = len(capture_spans) if capture_spans is not None else 0
                snap_sub = (
                    len(sub_capture_lists) if sub_capture_lists is not None else 0
                )
                result = _match_sequence(
                    remaining,
                    text,
                    current + n,
                    captures,
                    bindings,
                    capture_spans,
                    sub_capture_lists,
                )
                if isinstance(result, _SkipTo):
                    return result
                if result is not None:
                    # Insert wildcard capture at its natural left-to-right position
                    wc = text[current : current + n]
                    if captures is not None:
                        captures.insert(snap_c, wc)
                    if capture_spans is not None:
                        capture_spans.insert(snap_s, (current, current + n))
                    if sub_capture_lists is not None:
                        sub_capture_lists.insert(snap_sub, [wc])
                    return result
                if captures is not None:
                    del captures[snap_c:]
                if capture_spans is not None:
                    del capture_spans[snap_s:]
                if sub_capture_lists is not None:
                    del sub_capture_lists[snap_sub:]
            return None
        end = _match_node(
            node, text, current, captures, bindings, capture_spans, sub_capture_lists
        )
        if end is None:
            return None
        if isinstance(end, _SkipTo):
            return end
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
    options = _flatten_options(node.metadata.get("options", []))
    min_count, max_count, lazy = _parse_repetition(options, bindings)
    ctx = MatchCtx(
        _parse_case_insensitive(options), _parse_alphabet(options), _parse_pad(options)
    )

    # Multi-child bracket containing <<>> or <<sep>>: treat children as a sequence.
    # e.g. [hello<<>>world] or [hello<<,>>world]
    if len(node.children) > 1 and any(
        c.type == "double_chevrons" for c in node.children
    ):
        return _match_bracket_span(
            node.children,
            text,
            pos,
            captures,
            capture_spans,
            sub_capture_lists,
            min_count,
            max_count,
            lazy,
            ctx,
        )

    content = node.children[0]
    start_pos = pos
    positions = [pos]
    current = pos
    count = 0
    while max_count is None or count < max_count:
        end = _match_content(content, text, current, ctx)
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
        subs = [text[positions[i] : positions[i + 1]] for i in range(end_idx)]
        sub_capture_lists.append(subs)
    return result


def _match_bracket_span(
    children: list[HMKNode],
    text: str,
    pos: int,
    captures: list[str] | None,
    capture_spans: list[tuple[int, int]] | None,
    sub_capture_lists: list[list[str]] | None,
    min_count: int,
    max_count: int | None,
    lazy: bool,
    ctx: MatchCtx,
) -> int | None:
    """Handle [A<<>>B] / [A<<sep>>B] brackets: match children as an ordered sequence."""
    start_pos = pos
    current = pos
    count = 0
    all_subs: list[str] = []

    while max_count is None or count < max_count:
        end, subs = _match_span_children(children, text, current, ctx)
        if end is None or end == current:
            break
        count += 1
        all_subs.extend(subs)
        current = end

    if count < min_count:
        return None

    result = current
    if captures is not None:
        captures.append(text[start_pos:result])
    if capture_spans is not None:
        capture_spans.append((start_pos, result))
    if sub_capture_lists is not None:
        sub_capture_lists.append(all_subs)
    return result


def _match_span_children(
    children: list[HMKNode], text: str, pos: int, ctx: MatchCtx
) -> tuple[int | None, list[str]]:
    """Match a child sequence for span brackets; returns (end_pos, sub_captures)."""
    current = pos
    subs: list[str] = []

    for i, child in enumerate(children):
        if child.type == "double_chevrons":
            sep = _chevron_sep(child)
            remaining = children[i + 1 :]

            if not remaining:
                # Last item: consume everything left
                consumed = text[current:]
                subs.extend(consumed.split(sep) if sep else [consumed])
                return len(text), subs

            # Lazy: find minimum n so remaining matches from current+n
            for n in range(len(text) - current + 1):
                end, tail = _match_span_children(remaining, text, current + n, ctx)
                if end is not None:
                    consumed = text[current : current + n]
                    subs.extend(consumed.split(sep) if sep else [consumed])
                    subs.extend(tail)
                    return end, subs
            return None, []

        end = _match_content(child, text, current, ctx)
        if end is None:
            return None, []
        current = end

    return current, subs


def _match_bracket_negated(
    node: HMKNode,
    text: str,
    pos: int,
    captures: list[str] | None = None,
    bindings: dict[str, int] | None = None,
    capture_spans: list[tuple[int, int]] | None = None,
    sub_capture_lists: list[list[str]] | None = None,
) -> int | _SkipTo | None:
    if not node.children:
        return None
    content = node.children[0]
    options = _flatten_options(node.metadata.get("options", []))

    # Default when no count modifier: one or more, greedy (historic behaviour)
    has_count = any(
        o.type == "repetition_range"
        or (o.type == "option" and (o.content.isdigit() or _is_var(o.content)))
        for o in options
    )
    if has_count:
        min_count, max_count, lazy = _parse_repetition(options, bindings)
    else:
        min_count, max_count, lazy = 1, None, False

    # Build the run: consume characters that do NOT match the excluded content
    run_end = pos
    while (max_count is None or (run_end - pos) < max_count) and run_end < len(text):
        if _match_content(content, text, run_end, MatchCtx()) is not None:
            break
        run_end += 1

    run_length = run_end - pos

    if run_length < min_count:
        # Can't satisfy minimum — skip past the excluded content if it matched here
        inner_end = _match_content(content, text, pos, MatchCtx())
        if inner_end is not None and inner_end > pos:
            return _SkipTo(inner_end)
        return _SkipTo(pos + 1) if min_count > 0 else pos

    result = (pos + min_count) if lazy else run_end

    if captures is not None:
        captures.append(text[pos:result])
    if capture_spans is not None:
        capture_spans.append((pos, result))
    if sub_capture_lists is not None:
        sub_capture_lists.append(
            [text[pos + i : pos + i + 1] for i in range(result - pos)]
        )

    return result


# ---------------------------------------------------------------------------
# Content matchers
# ---------------------------------------------------------------------------


def _match_literal_node(
    node: HMKNode, text: str, pos: int, ctx: MatchCtx
) -> int | None:
    s = node.content
    if ctx.ci:
        return pos + len(s) if text[pos : pos + len(s)].lower() == s.lower() else None
    return pos + len(s) if text[pos : pos + len(s)] == s else None


def _match_shortcut_node(
    node: HMKNode, text: str, pos: int, _ctx: MatchCtx
) -> int | None:
    return _match_shortcut(node.metadata["kind"], text, pos)


def _match_range_node(node: HMKNode, text: str, pos: int, ctx: MatchCtx) -> int | None:
    return _match_range(
        node.metadata["start"],
        node.metadata["end"],
        text,
        pos,
        ctx.ci,
        ctx.alphabet,
        ctx.pad,
    )


def _match_alternation_node(
    node: HMKNode, text: str, pos: int, ctx: MatchCtx
) -> int | None:
    for arm in node.children:
        end = _match_content(arm, text, pos, ctx)
        if end is not None:
            return end
    return None


def _match_double_chevrons_node(
    node: HMKNode, text: str, pos: int, ctx: MatchCtx
) -> int | None:
    s = node.children[0].content if node.children else ""
    if not s:
        # <<>> inside brackets: match any single non-newline character
        return pos + 1 if pos < len(text) and text[pos] != "\n" else None
    # <<sep>> inside brackets: match the separator string as a literal
    if ctx.ci:
        return pos + len(s) if text[pos : pos + len(s)].lower() == s.lower() else None
    return pos + len(s) if text[pos : pos + len(s)] == s else None


_CONTENT_MATCHERS: dict[str, Callable[[HMKNode, str, int, MatchCtx], int | None]] = {
    "literal": _match_literal_node,
    "shortcut": _match_shortcut_node,
    "range": _match_range_node,
    "alternation": _match_alternation_node,
    "double_chevrons": _match_double_chevrons_node,
}


def _match_content(
    node: HMKNode, text: str, pos: int, ctx: MatchCtx = MatchCtx()
) -> int | None:
    if pos >= len(text):
        return None
    matcher = _CONTENT_MATCHERS.get(node.type)
    return matcher(node, text, pos, ctx) if matcher is not None else None


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


# ---------------------------------------------------------------------------
# Range matching
# ---------------------------------------------------------------------------


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
    if start.isdigit() and end.isdigit():
        return _match_integer_range(int(start), int(end), text, pos, pad)
    ch = text[pos]
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
            continue
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

    end_pos = pos
    while end_pos < len(text):
        ch = text[end_pos].lower() if case_agnostic else text[end_pos]
        if ch not in alpha:
            break
        end_pos += 1
    if end_pos == pos:
        return None
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


def _chevron_sep(node: HMKNode) -> str:
    """Return the separator string of a double_chevrons node (empty string for <<>>)."""
    return node.children[0].content if node.children else ""


def _has_explicit_count(options: list[HMKNode]) -> bool:
    """True when options contain an explicit repetition count or range."""
    return any(
        o.type == "repetition_range"
        or (o.type == "option" and (o.content.isdigit() or _is_var(o.content)))
        for o in options
    )


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
            min_count = (
                resolved_mn if resolved_mn is not None else (0 if not mn else min_count)
            )
            max_count = resolved_mx
        elif opt.type == "option":
            if opt.content.isdigit():
                min_count = max_count = int(opt.content)
            elif opt.content in _ALPHABETS or opt.content == "i":
                pass
            elif _is_var(opt.content) and bindings and opt.content in bindings:
                min_count = max_count = bindings[opt.content]
        elif opt.type == "lazy":
            lazy = True
    return min_count, max_count, lazy
