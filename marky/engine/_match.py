"""HMK match engine — walks the phase3 AST against a text string."""

from marky.engine._types import Match
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError
from marky.utils.alphabet import alpha_value

# Largest code-point range materialized into a value-arithmetic alphabet. ascii
# (128) fits; uni (1.1M) does not and raises when used as a range bound.
_MAX_MATERIALIZE = 0x10000


class _State:
    __slots__ = ("captures", "spans", "sub_groups", "count_refs")

    def __init__(self):
        self.captures: list[str] = []
        self.spans: list[tuple[int, int]] = []
        self.sub_groups: list[list[str]] = []
        self.count_refs: dict[int, int] = {}

    def snapshot(self):
        return (
            len(self.captures),
            len(self.spans),
            len(self.sub_groups),
            dict(self.count_refs),
        )

    def restore(self, snap):
        nc, ns, ng, cr = snap
        del self.captures[nc:]
        del self.spans[ns:]
        del self.sub_groups[ng:]
        self.count_refs.clear()
        self.count_refs.update(cr)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_matches(tree: t.RootNode, text: str) -> list[Match]:
    # Standalone separator: entire pattern is <<sep>> or <<>>
    if len(tree.children) == 1 and isinstance(tree.children[0], t.SeparatorNode):
        return _split_by_separator(tree.children[0], text)

    matches: list[Match] = []
    pos = 0
    while pos < len(text):
        state = _State()
        end = _match_sequence(tree.children, text, pos, state)
        if end is not None and end > pos:
            rel_spans = [(s - pos, e - pos) for s, e in state.spans]
            matches.append(
                Match(
                    text[pos:end],
                    pos,
                    end,
                    state.captures,
                    rel_spans,
                    state.sub_groups,
                    state.count_refs,
                )
            )
            pos = end
        else:
            pos += 1
    return matches


def _split_by_separator(node: t.SeparatorNode, text: str) -> list[Match]:
    if node.sep_class is not None:
        # α separator standalone: the span is the full input, constrained to
        # the class.
        if _unit_accepts(node.sep_class, text):
            return [Match(text, 0, len(text))]
        return []
    sep = node.sep_value if node.sep_value is not None else node.content
    if not sep:
        return [Match(text, 0, len(text))] if text else []
    parts = text.split(sep)
    result, pos = [], 0
    for part in parts:
        result.append(Match(part, pos, pos + len(part)))
        pos += len(part) + len(sep)
    return result


# ---------------------------------------------------------------------------
# Sequence matching
# ---------------------------------------------------------------------------


def _match_sequence(
    nodes: list[t.Node], text: str, pos: int, state: _State
) -> int | None:
    current = pos
    i = 0
    while i < len(nodes):
        node = nodes[i]

        # Separator: lazy span. α content constrains the span to the class;
        # τ content splits the span into sub-captures; empty is unconstrained.
        if isinstance(node, t.SeparatorNode):
            remaining = nodes[i + 1 :]
            snap = state.snapshot()
            cls = node.sep_class
            sep_val = node.sep_value
            if not remaining:
                wc = text[current:]
                if cls is not None and not _unit_accepts(cls, wc):
                    return None
                _record_sep_capture(state, wc, current, len(text), sep_val)
                return len(text)
            for n in range(len(text) - current + 1):
                wc = text[current : current + n]
                if cls is not None and not _unit_accepts(cls, wc):
                    continue
                state.restore(snap)
                end = _match_sequence(remaining, text, current + n, state)
                if end is not None:
                    _insert_sep_capture(state, snap, wc, current, current + n, sep_val)
                    return end
            state.restore(snap)
            return None

        end = _match_node(node, text, current, state)
        if end is None:
            return None
        current = end
        i += 1
    return current


def _sep_sub_groups(wc: str, sep_val: str | None) -> list[str]:
    """τ split semantics: the span's sub-captures are its sep-split segments."""
    return wc.split(sep_val) if sep_val else [wc]


def _record_sep_capture(
    state: _State, text: str, start: int, end: int, sep_val: str | None = None
):
    state.captures.append(text)
    state.spans.append((start, end))
    state.sub_groups.append(_sep_sub_groups(text, sep_val))


def _insert_sep_capture(
    state: _State,
    snap: tuple,
    wc: str,
    start: int,
    end: int,
    sep_val: str | None = None,
):
    nc = snap[0]
    state.captures.insert(nc, wc)
    state.spans.insert(snap[1], (start, end))
    state.sub_groups.insert(snap[2], _sep_sub_groups(wc, sep_val))


# ---------------------------------------------------------------------------
# Node dispatch
# ---------------------------------------------------------------------------


def _match_node(node: t.Node, text: str, pos: int, state: _State) -> int | None:
    if isinstance(node, t.RootNode):
        return _match_sequence(node.children, text, pos, state)
    if isinstance(node, t.BraceGroupNode):
        return _match_brace_group(node, text, pos, state)
    if isinstance(node, t.LeafNode):
        s = node.content
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    # Semantic nodes used inside brace_group — shouldn't appear naked in sequence
    if t.is_semantic(node):
        return _match_semantic(node, text, pos)
    return None


def _count_config(node: t.BraceGroupNode) -> tuple[int, int | None, int | None]:
    """Return (min_reps, max_reps, count_ref) from a brace-group count."""
    count = node.count
    if isinstance(count, t.CountRange):
        return count.min, count.max, None
    if isinstance(count, t.CountRef):
        return 1, 1, count.index
    return 1, 1, None


def _match_brace_group(
    node: t.BraceGroupNode, text: str, pos: int, state: _State
) -> int | None:
    if node.semantic is None:
        return None
    semantic = node.semantic
    min_reps, max_reps, count_ref = _count_config(node)

    # Resolve count_ref ({{#N}} in count position)
    if count_ref is not None:
        n = state.count_refs.get(count_ref, 0)
        min_reps = max_reps = n

    is_zip = isinstance(semantic, (t.ZipRangeNode, t.GroupClassNode))

    def record(end: int, subs: list[str]) -> int:
        idx = len(state.captures)
        state.captures.append(text[pos:end])
        state.spans.append((pos, end))
        state.sub_groups.append(subs)
        state.count_refs[idx] = len(subs)
        return end

    greedy_end = _match_semantic(semantic, text, pos)
    if greedy_end is None or greedy_end == pos:
        # No unit matches here; only a zero-or-more count tolerates that.
        return record(pos, []) if min_reps == 0 else None

    # Repetition with value equality: the first unit need not be greedy-maximal.
    # A shorter first unit may let the remainder split into equal repetitions
    # (e.g. "2525" → 25+25, "abAB" → ab+AB). Try lengths longest-first and take
    # the first that satisfies the count.
    max_unit_len = greedy_end - pos
    for unit_len in range(max_unit_len, 0, -1):
        first_val = text[pos : pos + unit_len]
        if not _unit_accepts(semantic, first_val):
            continue
        subs = [first_val]
        current = pos + unit_len
        while max_reps is None or len(subs) < max_reps:
            nxt = _match_equal_block(semantic, text, current, first_val, is_zip)
            if nxt is None:
                break
            subs.append(text[current:nxt])
            current = nxt
        if len(subs) >= min_reps:
            return record(current, subs)

    return record(pos, []) if min_reps == 0 else None


def _unit_accepts(semantic: t.SemanticNode, s: str) -> bool:
    """True if `semantic` matches the exact string `s` as a single unit."""
    return bool(s) and _match_semantic(semantic, s, 0) == len(s)


def _match_equal_block(
    semantic: t.SemanticNode, text: str, pos: int, first_val: str, is_zip: bool
) -> int | None:
    """Match one more repetition that must equal `first_val` (congruence-aware
    for zip_range / group_class, literal otherwise)."""
    if isinstance(semantic, t.GroupClassNode):
        return _match_group_equal(semantic, text, pos, first_val)
    if isinstance(semantic, t.ZipRangeNode):
        return _match_zip_equal(semantic, text, pos, first_val)
    n = len(first_val)
    return pos + n if text[pos : pos + n] == first_val else None


# ---------------------------------------------------------------------------
# Semantic node matchers
# ---------------------------------------------------------------------------


def _match_semantic(node: t.SemanticNode, text: str, pos: int) -> int | None:
    if pos >= len(text):
        return None
    if isinstance(node, t.LiteralNode):
        s = node.content
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if isinstance(node, t.CharRangeNode):
        ch = text[pos]
        if not (node.start <= ch <= node.end):
            return None
        if node.exclusions and _is_char_excluded(ch, node.exclusions):
            return None
        return pos + 1
    if isinstance(node, t.StringRangeNode):
        return _match_string_range(node, text, pos)
    if isinstance(node, t.FullAlphaNode):
        return _match_full_alpha(node, text, pos)
    if isinstance(node, (t.UpperBoundNode, t.LowerBoundNode, t.BoundedRangeNode)):
        return _match_value_range(node, text, pos)
    if isinstance(node, t.ZipRangeNode):
        return _match_zip_range(node, text, pos)
    if isinstance(node, t.UnionNode):
        return _match_union(node, text, pos)
    if isinstance(node, t.ComplementNode):
        return _match_complement(node, text, pos)
    if isinstance(node, t.TokenSetNode):
        return _match_token_set(node, text, pos)
    if isinstance(node, t.GroupClassNode):
        return _match_group_class(node, text, pos)
    if isinstance(node, t.PaddedNode):
        return _match_padded(node, text, pos)
    return None


def _match_string_range(node: t.StringRangeNode, text: str, pos: int) -> int | None:
    """Greedy lex-range match for multi-char τ..τ endpoints.

    When endpoints are equal length, only that length is tried.
    When different, tries lengths from len(end) down to len(start).
    """
    start, end = node.start, node.end
    lo_len = min(len(start), len(end))
    hi_len = max(len(start), len(end))
    for length in range(hi_len, lo_len - 1, -1):
        s = text[pos : pos + length]
        if len(s) < length:
            continue
        if start <= s <= end:
            return pos + length
    return None


def _match_full_alpha(node: t.FullAlphaNode, text: str, pos: int) -> int | None:
    """Greedy: consume 1+ chars that each match the inner alpha node."""
    inner = node.inner
    excl = node.exclusions
    end = pos
    while end < len(text):
        if excl and _is_char_excluded(text[end], excl):
            break
        next_end = _match_semantic(inner, text, end)
        if next_end is None or next_end == end:
            break
        end = next_end
    return end if end > pos else None


def _alpha_str(node: t.SemanticNode) -> str:
    """Extract the alphabet string for range-value comparisons."""
    if isinstance(node, t.CharRangeNode):
        s, e = node.start, node.end
        if ord(e) - ord(s) + 1 > _MAX_MATERIALIZE:
            raise CompileError(
                f"Range {s!r}..{e!r} is too large to use as a value bound"
            )
        return "".join(chr(c) for c in range(ord(s), ord(e) + 1))
    if isinstance(node, t.UnionNode):
        s = "".join(_alpha_str(ch) for ch in node.options)
        if len(set(s)) != len(s):
            raise CompileError(
                "Alphabet has duplicate symbols — symbol values would be "
                "ambiguous; use congruence (<->) for case-folding"
            )
        return s
    if isinstance(node, t.LiteralNode):
        return node.content
    raise ValueError(f"Cannot extract alphabet from {type(node).__name__}")


def _value_bounds(
    node: t.SemanticNode,
) -> tuple[str, int | None, int | None, list[str], int]:
    """Return (alphabet, lo, hi, exclusions, min_width) for a value-range node.

    lo / hi are None when that side is unbounded. Exclusions are raw strings
    (a single value or a `v1..v2` sub-range) checked numerically at match time.
    min_width is the written width of the lower endpoint (1 when there is
    none): values are zero-padded to it, so `{aa..{a..z}..zz}` matches exactly
    the 2-char lowercase strings.
    """
    if isinstance(node, t.UpperBoundNode):
        alph = _alpha_str(node.alpha)
        return alph, None, alpha_value(node.upper, alph), node.exclusions, 1
    if isinstance(node, t.LowerBoundNode):
        alph = _alpha_str(node.alpha)
        lo = alpha_value(node.lower, alph)
        return alph, lo, None, node.exclusions, len(node.lower)
    if isinstance(node, t.BoundedRangeNode):
        alph = _alpha_str(node.alpha)
        lo = alpha_value(node.lower, alph)
        hi = alpha_value(node.upper, alph)
        return alph, lo, hi, node.exclusions, len(node.lower)
    if isinstance(node, t.FullAlphaNode):
        return _alpha_str(node.inner), None, None, node.exclusions, 1
    raise ValueError(f"{type(node).__name__} has no value bounds")


def _canonical_len(value: int, base: int) -> int:
    """Width of `value` written canonically (no leading zeros) in `base`."""
    length, ceiling = 1, base
    while value >= ceiling:
        ceiling *= base
        length += 1
    return length


def _is_char_excluded(ch: str, exclusions: list[str]) -> bool:
    """Return True if single character `ch` falls in any excluded character or char-range."""
    for excl in exclusions:
        if ".." in excl:
            lo, hi = excl.split("..", 1)
            if lo <= ch <= hi:
                return True
        elif ch == excl:
            return True
    return False


def _is_value_excluded(v: int, alph: str, exclusions: list[str]) -> bool:
    """Return True if integer value `v` falls in any excluded value or sub-range."""
    for excl in exclusions:
        if ".." in excl:
            lo_s, hi_s = excl.split("..", 1)
            if alpha_value(lo_s, alph) <= v <= alpha_value(hi_s, alph):
                return True
        elif v == alpha_value(excl, alph):
            return True
    return False


def _match_value_range(node: t.SemanticNode, text: str, pos: int) -> int | None:
    """Greedy canonical-form match: each value has exactly one representation —
    no leading zero symbols beyond zero-padding up to the lower endpoint's
    written width (min_w)."""
    alph, lo, hi, excl, min_w = _value_bounds(node)
    zero = alph[0]
    end = pos
    while end < len(text) and text[end] in alph:
        end += 1
    for length in range(end - pos, min_w - 1, -1):
        candidate = text[pos : pos + length]
        if length > min_w and candidate[0] == zero:
            continue
        v = alpha_value(candidate, alph)
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            continue
        if _is_value_excluded(v, alph, excl):
            continue
        return pos + length
    return None


def _build_zip_groups(node: t.ZipRangeNode) -> list[list[str]]:
    """Expand zip_range into a list of groups (one list of equivalent chars each)."""
    try:
        left_alph = _alpha_str(node.left)
        right_alph = _alpha_str(node.right)
    except (ValueError, CompileError):
        return []

    if len(left_alph) != len(right_alph):
        return []  # Zip requires equal-length alphabets

    # Each position i in left corresponds to position i in right, but left and
    # right are multi-member groups (e.g. {a,A} and {z,Z}) expanded in parallel.
    left_members = _group_members(node.left)
    right_members = _group_members(node.right)
    if len(left_members) != len(right_members):
        return []

    # Each member is a single-char string; build ranges between left[j], right[j].
    member_ranges = []
    for lm, rm in zip(left_members, right_members):
        if len(lm) != 1 or len(rm) != 1:
            return []
        lo, hi = ord(lm), ord(rm)
        if lo > hi:
            lo, hi = hi, lo
        member_ranges.append((lo, hi))

    if not member_ranges:
        return []

    # All ranges must have the same length.
    range_len = member_ranges[0][1] - member_ranges[0][0] + 1
    if any((hi - lo + 1) != range_len for lo, hi in member_ranges):
        return []

    return [[chr(lo + i) for lo, _ in member_ranges] for i in range(range_len)]


def _group_members(node: t.SemanticNode) -> list[str]:
    """Extract the individual character members from a simple alpha node."""
    if isinstance(node, t.LiteralNode):
        return [node.content]
    if isinstance(node, t.CharRangeNode):
        return [chr(c) for c in range(ord(node.start), ord(node.end) + 1)]
    if isinstance(node, t.UnionNode):
        result = []
        for child in node.options:
            result.extend(_group_members(child))
        return result
    return []


def _match_zip_range(node: t.ZipRangeNode, text: str, pos: int) -> int | None:
    groups = _build_zip_groups(node)
    if not groups:
        return None
    char_set = {ch for grp in groups for ch in grp}
    end = pos
    while end < len(text) and text[end] in char_set:
        end += 1
    return end if end > pos else None


def _match_zip_equal(
    node: t.ZipRangeNode, text: str, pos: int, first_val: str
) -> int | None:
    """Match a zip_range repetition that must be group-equivalent to first_val."""
    groups = _build_zip_groups(node)
    if not groups or len(first_val) == 0:
        return None

    char_to_group = {}
    for idx, grp in enumerate(groups):
        for ch in grp:
            char_to_group[ch] = idx

    # Normalize first_val to a group-index sequence.
    first_groups = []
    for ch in first_val:
        if ch not in char_to_group:
            return None
        first_groups.append(char_to_group[ch])

    candidate = text[pos : pos + len(first_val)]
    if len(candidate) != len(first_val):
        return None
    for ch, expected_grp in zip(candidate, first_groups):
        if char_to_group.get(ch) != expected_grp:
            return None
    return pos + len(first_val)


def _match_group_equal(
    node: t.GroupClassNode, text: str, pos: int, first_val: str
) -> int | None:
    """Match a group_class repetition that must be group-equivalent to first_val.

    Single-char members map each char to its group index; the repetition is equal
    when it has the same group sequence (so `a<->A` makes 'a' and 'A' equal). If
    any member is multi-char, fall back to literal equality.
    """
    char_to_group: dict[str, int] = {}
    for idx, grp in enumerate(node.groups):
        for m in grp:
            if len(m) != 1:
                n = len(first_val)
                return pos + n if text[pos : pos + n] == first_val else None
            char_to_group[m] = idx
    n = len(first_val)
    candidate = text[pos : pos + n]
    if len(candidate) != n:
        return None
    for a, b in zip(first_val, candidate):
        if a not in char_to_group or char_to_group.get(b) != char_to_group[a]:
            return None
    return pos + n


def _match_union(node: t.UnionNode, text: str, pos: int) -> int | None:
    excl = node.exclusions
    for arm in node.options:
        end = _match_semantic(arm, text, pos)
        if end is not None:
            val = text[pos:end]
            if not _is_excluded(val, excl):
                return end
    return None


def _is_excluded(val: str, exclusions: list[str]) -> bool:
    """Return True if val matches any exclusion (single value or range)."""
    for excl in exclusions:
        if ".." in excl:
            lo, hi = excl.split("..", 1)
            if lo <= val <= hi:
                return True
        elif val == excl:
            return True
    return False


def _match_complement(node: t.ComplementNode, text: str, pos: int) -> int | None:
    """Greedily consume chars NOT matching the inner node."""
    inner = node.inner
    end = pos
    while end < len(text):
        if _match_semantic(inner, text, end) is not None:
            break
        end += 1
    return end if end > pos else None


def _match_token_set(node: t.TokenSetNode, text: str, pos: int) -> int | None:
    tokens = sorted(node.tokens, key=len, reverse=True)
    excl = node.exclusions
    for token in tokens:
        if text[pos : pos + len(token)] == token and token not in excl:
            return pos + len(token)
    return None


def _match_group_class(node: t.GroupClassNode, text: str, pos: int) -> int | None:
    """Match a sequence of group members (tokens), each possibly multi-char.

    Every consumed position must be a whole token belonging to one of the
    groups — not merely a character drawn from the union of all members.
    Tokens are tried longest-first so multi-char members win over any shorter
    member that is a prefix of them.
    """
    tokens = sorted(
        (item for grp in node.groups for item in grp if item),
        key=len,
        reverse=True,
    )
    end = pos
    while end < len(text):
        for tok in tokens:
            if text[end : end + len(tok)] == tok:
                end += len(tok)
                break
        else:
            break
    return end if end > pos else None


def _match_padded(node: t.PaddedNode, text: str, pos: int) -> int | None:
    """Width-window match: widths max_width down to min_width, leading
    zero-character padding allowed throughout (that is the point of padding).
    A None max_width ({:expr}) derives from the inner range's maximum value."""
    inner = node.inner
    try:
        alph, lo, hi, excl, _ = _value_bounds(inner)
    except ValueError:
        return _match_padded_per_char(node, text, pos)

    run = pos
    while run < len(text) and text[run] in alph:
        run += 1
    max_w = node.max_width
    if max_w is None:
        max_w = _canonical_len(hi, len(alph)) if hi is not None else run - pos
    for width in range(min(max_w, run - pos), node.min_width - 1, -1):
        v = alpha_value(text[pos : pos + width], alph)
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            continue
        if _is_value_excluded(v, alph, excl):
            continue
        return pos + width
    return None


def _match_padded_per_char(node: t.PaddedNode, text: str, pos: int) -> int | None:
    """Inner is not a value-range node (e.g. a char union): the width window
    applies to a run of single-char inner matches."""
    inner = node.inner
    run = pos
    while run < len(text) and _match_semantic(inner, text, run) == run + 1:
        run += 1
    max_w = node.max_width if node.max_width is not None else run - pos
    width = min(max_w, run - pos)
    return pos + width if width >= node.min_width else None
