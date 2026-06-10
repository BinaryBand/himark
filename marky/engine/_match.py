"""HMK match engine — walks the phase3 AST against a text string."""

from marky.engine._types import Match
from marky.models.node import HMKNode
from marky.utils.alphabet import NAMED_ALPHABETS, alpha_value


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


def find_matches(tree: HMKNode, text: str) -> list[Match]:
    # Standalone separator: entire pattern is <<sep>> or <<>>
    if (
        tree.type == "root"
        and len(tree.children) == 1
        and tree.children[0].type == "separator"
    ):
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


def _split_by_separator(node: HMKNode, text: str) -> list[Match]:
    sep = node.content
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
    nodes: list[HMKNode], text: str, pos: int, state: _State
) -> int | None:
    current = pos
    i = 0
    while i < len(nodes):
        node = nodes[i]

        # Separator acting as lazy wildcard
        if node.type == "separator":
            remaining = nodes[i + 1 :]
            snap = state.snapshot()
            if not remaining:
                wc = text[current:]
                _record_sep_capture(state, wc, current, len(text))
                return len(text)
            for n in range(len(text) - current + 1):
                state.restore(snap)
                end = _match_sequence(remaining, text, current + n, state)
                if end is not None:
                    wc = text[current : current + n]
                    _insert_sep_capture(state, snap, wc, current, current + n)
                    return end
            state.restore(snap)
            return None

        end = _match_node(node, text, current, state)
        if end is None:
            return None
        current = end
        i += 1
    return current


def _record_sep_capture(state: _State, text: str, start: int, end: int):
    state.captures.append(text)
    state.spans.append((start, end))
    state.sub_groups.append([text])


def _insert_sep_capture(state: _State, snap: tuple, wc: str, start: int, end: int):
    nc = snap[0]
    state.captures.insert(nc, wc)
    state.spans.insert(snap[1], (start, end))
    state.sub_groups.insert(snap[2], [wc])


# ---------------------------------------------------------------------------
# Node dispatch
# ---------------------------------------------------------------------------


def _match_node(node: HMKNode, text: str, pos: int, state: _State) -> int | None:
    t = node.type
    if t == "root":
        return _match_sequence(node.children, text, pos, state)
    if t == "brace_group":
        return _match_brace_group(node, text, pos, state)
    if t == "leaf":
        s = node.content
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    # Semantic nodes used inside brace_group — shouldn't appear naked in sequence
    return _match_semantic(node, text, pos)


def _match_brace_group(node: HMKNode, text: str, pos: int, state: _State) -> int | None:
    if not node.children:
        return None
    semantic = node.children[0]
    count = node.metadata.get("count", {"min": 1, "max": 1})

    min_reps = count.get("min", 1)
    max_reps = count.get("max", 1)
    count_ref = count.get("count_ref")

    # Resolve count_ref ({{#N}} in count position)
    if count_ref is not None:
        n = state.count_refs.get(count_ref, 0)
        min_reps = max_reps = n

    is_zip = semantic.type == "zip_range"

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


def _unit_accepts(semantic: HMKNode, s: str) -> bool:
    """True if `semantic` matches the exact string `s` as a single unit."""
    return bool(s) and _match_semantic(semantic, s, 0) == len(s)


def _match_equal_block(
    semantic: HMKNode, text: str, pos: int, first_val: str, is_zip: bool
) -> int | None:
    """Match one more repetition that must equal `first_val` (group-equal if zip)."""
    if is_zip:
        return _match_zip_equal(semantic, text, pos, first_val)
    n = len(first_val)
    return pos + n if text[pos : pos + n] == first_val else None


# ---------------------------------------------------------------------------
# Semantic node matchers
# ---------------------------------------------------------------------------


def _match_semantic(node: HMKNode, text: str, pos: int) -> int | None:
    if pos >= len(text):
        return None
    t = node.type
    if t == "literal":
        s = node.content
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if t == "char_range":
        ch = text[pos]
        if not (node.metadata["start"] <= ch <= node.metadata["end"]):
            return None
        excl = node.metadata.get("exclusions", [])
        if excl and _is_char_excluded(ch, excl):
            return None
        return pos + 1
    if t == "string_range":
        return _match_string_range(node, text, pos)
    if t == "named_alpha":
        return _match_named_alpha(node, text, pos)
    if t == "full_alpha":
        return _match_full_alpha(node, text, pos)
    if t == "upper_bound":
        return _match_upper_bound(node, text, pos)
    if t == "lower_bound":
        return _match_lower_bound(node, text, pos)
    if t == "bounded_range":
        return _match_bounded_range(node, text, pos)
    if t == "zip_range":
        return _match_zip_range(node, text, pos)
    if t == "union":
        return _match_union(node, text, pos)
    if t == "complement":
        return _match_complement(node, text, pos)
    if t == "token_set":
        return _match_token_set(node, text, pos)
    if t == "group_class":
        return _match_group_class(node, text, pos)
    if t == "padded":
        return _match_padded(node, text, pos)
    return None


def _match_string_range(node: HMKNode, text: str, pos: int) -> int | None:
    """Greedy lex-range match for multi-char τ..τ endpoints.

    When endpoints are equal length, only that length is tried.
    When different, tries lengths from len(end) down to len(start).
    """
    start = node.metadata["start"]
    end = node.metadata["end"]
    lo_len = min(len(start), len(end))
    hi_len = max(len(start), len(end))
    for length in range(hi_len, lo_len - 1, -1):
        s = text[pos : pos + length]
        if len(s) < length:
            continue
        if start <= s <= end:
            return pos + length
    return None


def _match_named_alpha(node: HMKNode, text: str, pos: int) -> int | None:
    name = node.metadata["name"]
    alph = NAMED_ALPHABETS[name]
    ch = text[pos]
    if alph is None:
        # Virtual: ascii or uni
        if name == "ascii":
            if ord(ch) > 0x7F:
                return None
        elif name == "uni":
            pass  # every char is in uni
        else:
            return None
    elif ch not in alph:
        return None
    excl = node.metadata.get("exclusions", [])
    if excl and _is_char_excluded(ch, excl):
        return None
    return pos + 1


def _match_full_alpha(node: HMKNode, text: str, pos: int) -> int | None:
    """Greedy: consume 1+ chars that each match the inner alpha node."""
    inner = node.children[0]
    excl = node.metadata.get("exclusions", [])
    end = pos
    while end < len(text):
        if excl and _is_char_excluded(text[end], excl):
            break
        next_end = _match_semantic(inner, text, end)
        if next_end is None or next_end == end:
            break
        end = next_end
    return end if end > pos else None


def _alpha_str(node: HMKNode) -> str:
    """Extract the alphabet string for range-value comparisons."""
    t = node.type
    if t == "named_alpha":
        name = node.metadata["name"]
        alph = NAMED_ALPHABETS[name]
        if alph is None:
            raise ValueError(f"Virtual alphabet {name!r} cannot be used as range bound")
        return alph
    if t == "char_range":
        s, e = node.metadata["start"], node.metadata["end"]
        return "".join(chr(c) for c in range(ord(s), ord(e) + 1))
    if t == "union":
        return "".join(_alpha_str(ch) for ch in node.children)
    if t == "literal":
        return node.content
    raise ValueError(f"Cannot extract alphabet from node type {t!r}")


def _value_bounds(
    node: HMKNode,
) -> tuple[str, int | None, int | None, list[str]]:
    """Return (alphabet, lo, hi, exclusions) for a value-range node.

    lo / hi are None when that side is unbounded. Exclusions are raw strings
    (a single value or a `v1..v2` sub-range) checked numerically at match time.
    """
    t = node.type
    excl = node.metadata.get("exclusions", [])
    if t == "upper_bound":
        alph = _alpha_str(node.metadata["alpha"])
        return alph, None, alpha_value(node.metadata["upper"], alph), excl
    if t == "lower_bound":
        alph = _alpha_str(node.metadata["alpha"])
        return alph, alpha_value(node.metadata["lower"], alph), None, excl
    if t == "bounded_range":
        alph = _alpha_str(node.metadata["alpha"])
        lo = alpha_value(node.metadata["lower"], alph)
        hi = alpha_value(node.metadata["upper"], alph)
        return alph, lo, hi, excl
    if t == "full_alpha":
        alph = _alpha_str(node.children[0])
        return alph, None, None, excl
    if t == "named_alpha":
        return _alpha_str(node), None, None, excl
    raise ValueError(f"Node type {t!r} has no value bounds")


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


def _match_alpha_value_range(
    alph: str,
    lo: int | None,
    hi: int | None,
    exclusions: list[str],
    text: str,
    pos: int,
) -> int | None:
    """Greedily consume alphabet chars at pos; return longest end where lo ≤ val ≤ hi."""
    end = pos
    while end < len(text) and text[end] in alph:
        end += 1
    if end == pos:
        return None
    for length in range(end - pos, 0, -1):
        candidate = text[pos : pos + length]
        v = alpha_value(candidate, alph)
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            continue
        if _is_value_excluded(v, alph, exclusions):
            continue
        return pos + length
    return None


def _match_upper_bound(node: HMKNode, text: str, pos: int) -> int | None:
    alph, lo, hi, excl = _value_bounds(node)
    return _match_alpha_value_range(alph, lo, hi, excl, text, pos)


def _match_lower_bound(node: HMKNode, text: str, pos: int) -> int | None:
    alph, lo, hi, excl = _value_bounds(node)
    return _match_alpha_value_range(alph, lo, hi, excl, text, pos)


def _match_bounded_range(node: HMKNode, text: str, pos: int) -> int | None:
    alph, lo, hi, excl = _value_bounds(node)
    return _match_alpha_value_range(alph, lo, hi, excl, text, pos)


def _build_zip_groups(node: HMKNode) -> list[list[str]]:
    """Expand zip_range into a list of groups (one list of equivalent chars each)."""
    left_node = node.metadata["left"]
    right_node = node.metadata["right"]

    try:
        left_alph = _alpha_str(left_node)
        right_alph = _alpha_str(right_node)
    except ValueError:
        return []

    if len(left_alph) != len(right_alph):
        # Zip requires equal-length alphabets
        return []

    groups: list[list[str]] = []
    # Each position i in left corresponds to position i in right
    # But left and right are multi-member groups (e.g., {a,A} and {z,Z})
    # The sub-members must be expanded in parallel
    left_members = _group_members(left_node)
    right_members = _group_members(right_node)

    if len(left_members) != len(right_members):
        return []

    # Each member is a single-char string; build ranges between left[j] and right[j]
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

    # All ranges must have the same length
    range_len = member_ranges[0][1] - member_ranges[0][0] + 1
    if any((hi - lo + 1) != range_len for lo, hi in member_ranges):
        return []

    for i in range(range_len):
        groups.append([chr(lo + i) for lo, _ in member_ranges])

    return groups


def _group_members(node: HMKNode) -> list[str]:
    """Extract the individual character members from a simple alpha node."""
    t = node.type
    if t == "literal":
        return [node.content]
    if t == "char_range":
        s, e = node.metadata["start"], node.metadata["end"]
        return [chr(c) for c in range(ord(s), ord(e) + 1)]
    if t == "named_alpha":
        alph = NAMED_ALPHABETS[node.metadata["name"]]
        return list(alph) if alph else []
    if t == "union":
        result = []
        for child in node.children:
            result.extend(_group_members(child))
        return result
    return []


def _match_zip_range(node: HMKNode, text: str, pos: int) -> int | None:
    groups = _build_zip_groups(node)
    if not groups:
        return None
    char_set = {ch for grp in groups for ch in grp}
    end = pos
    while end < len(text) and text[end] in char_set:
        end += 1
    return end if end > pos else None


def _match_zip_equal(node: HMKNode, text: str, pos: int, first_val: str) -> int | None:
    """Match a zip_range repetition that must be group-equivalent to first_val."""
    groups = _build_zip_groups(node)
    if not groups or len(first_val) == 0:
        return None

    char_to_group = {}
    for idx, grp in enumerate(groups):
        for ch in grp:
            char_to_group[ch] = idx

    # Normalize first_val to group index sequence
    first_groups = []
    for ch in first_val:
        if ch not in char_to_group:
            return None
        first_groups.append(char_to_group[ch])

    # Check that text[pos:pos+len(first_val)] has the same group sequence
    candidate = text[pos : pos + len(first_val)]
    if len(candidate) != len(first_val):
        return None
    for ch, expected_grp in zip(candidate, first_groups):
        if char_to_group.get(ch) != expected_grp:
            return None
    return pos + len(first_val)


def _match_union(node: HMKNode, text: str, pos: int) -> int | None:
    excl = node.metadata.get("exclusions", [])
    for arm in node.children:
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
            parts = excl.split("..", 1)
            lo, hi = parts[0], parts[1]
            if lo <= val <= hi:
                return True
        elif val == excl:
            return True
    return False


def _match_complement(node: HMKNode, text: str, pos: int) -> int | None:
    """Greedily consume chars NOT matching the inner node."""
    inner = node.children[0]
    end = pos
    while end < len(text):
        if _match_semantic(inner, text, end) is not None:
            break
        end += 1
    return end if end > pos else None


def _match_token_set(node: HMKNode, text: str, pos: int) -> int | None:
    tokens = sorted(node.metadata["tokens"], key=len, reverse=True)
    excl = node.metadata.get("exclusions", [])
    for token in tokens:
        if text[pos : pos + len(token)] == token and token not in excl:
            return pos + len(token)
    return None


def _match_group_class(node: HMKNode, text: str, pos: int) -> int | None:
    groups = node.metadata["groups"]
    char_set = {ch for grp in groups for item in grp for ch in item}
    end = pos
    while end < len(text) and text[end] in char_set:
        end += 1
    return end if end > pos else None


def _match_padded(node: HMKNode, text: str, pos: int) -> int | None:
    inner = node.children[0]
    width = node.metadata.get("width")

    if width is not None:
        # Fixed width: exactly `width` chars, all in the alphabet, value in bounds.
        # Leading zero-character padding is allowed (that is the point of padding).
        candidate = text[pos : pos + width]
        if len(candidate) != width:
            return None
        try:
            alph, lo, hi, excl = _value_bounds(inner)
        except ValueError:
            # Inner is not a value-range node (e.g. a char union): accept each
            # position individually.
            if all(
                _match_semantic(inner, text, pos + i) == pos + i + 1
                for i in range(width)
            ):
                return pos + width
            return None
        if not all(c in alph for c in candidate):
            return None
        v = alpha_value(candidate, alph)
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            return None
        if _is_value_excluded(v, alph, excl):
            return None
        return pos + width

    # Variable width ({: expr}): the inner value range already greedily caps at
    # len(max) and allows leading zeros, so delegate directly.
    return _match_semantic(inner, text, pos)
