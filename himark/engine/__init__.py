"""Direct execution engine for parsed HMK expressions.

A `=>` chain is `step => step => ...`, where each step is a **query** (a matcher)
or a **template** (plain text with no matchable `{...}`).

Execution is a **branch model**. The first step bootstraps the branches: a **query**
starts one per match, while a leading **template** starts a single branch over the
whole document (`{{.}}` is the entire input). The rest of the chain transforms each
branch's text independently:

* a **query** matches within the branch's text and splices each match's transform
  back in place (keeping the text between matches); a query that matches nothing
  drops the branch — that is how filtering works;
* a **template** renders, and the chain continues on its render — so templates are
  *not* terminal: a later query matches the rendered text, and a later template
  wraps it (`{{.}}` is the flowing text, so templates compose).

Stages are numbered by `=>` position; each step (query or template) appends one,
so `{{ i$j }}` / `{N$M}` address any earlier step by position.

The branches render two ways, neither privileged:

* `execute` — the **list** of branch results (one per surviving branch).
* `splice`  — the source with each branch's span replaced by its result, the text
  between branches kept verbatim (in-place transform).
"""


from himark.engine._render import render as _render
from himark.engine.backend import Match
from himark import parser
from himark.prelude import VARIABLES
from himark.engine.runtime import Runtime
from himark.models.compiled import Program, Step, Template
from himark.models.exceptions import CompileError

# A step is a template (rendered) when it is a `Template`, else a query `Program`
# (matched). `isinstance(step, Template)` is used inline at the dispatch sites so
# the type checker narrows `Step` to the right arm in each branch.

__all__ = [
    "execute",
    "splice",
    "splice_to_fixed_point",
    "run_pipeline",
    "deltas",
    "find",
    "find_matches",
    "Match",
]

# The default runtime owns the active matching backend and the per-program handle
# The default runtime — holds the per-Program instruction cache.
_runtime = Runtime()


def find_matches(
    program: Program,
    target: str,
    stages: tuple[Match, ...] = (),
    start: int = 0,
    stop: int | None = None,
) -> list[Match]:
    """Return all matches of a compiled query `program` in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve;
    `start`/`stop` bound the positions a match may begin at."""
    return _runtime.find_matches(program, target, stages, start, stop)


def find(steps: list[Step], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target. A leading
    template is the whole-document branch, so its span is the whole input."""
    head = steps[0]
    if isinstance(head, Template):
        return [(0, len(target))]
    return [(m.start, m.end) for m in find_matches(head, target)]


# ── Branch building ───────────────────────────────────────────────────────────


def _transform(
    steps: list[Step],
    text: str,
    ancestors: tuple[Match, ...],
    committed: bool = False,
) -> str | None:
    """Transform `text` through the rest of the chain, returning the branch's
    result — its **committed** output. `ancestors` is the chain of stage matches
    so far; `committed` is True once a template upstream has rendered.

    Eager-commit: a template renders and **commits** that render (the chain
    continues on it, never rolled back). A query splices each match's transform
    in place; a query that matches nothing keeps the committed text if a template
    has rendered, else drops the branch — that is how a guard filters."""
    if not steps:
        return text
    head, rest = steps[0], steps[1:]

    if isinstance(head, Template):
        full, spans = _render(head, text, list(ancestors))
        if spans is None:  # no moustaches — the whole render flows on as one branch
            stage = Match(full, 0, len(full), [])
            return _transform(rest, full, (*ancestors, stage), committed=True)
        if not rest:
            return full
        # Each moustache is a branch: its value flows downstream and its result is
        # spliced back over its own span, keeping the decoration between (the same
        # splice the query branch below runs, with moustaches playing the matches).
        pieces: list[str] = []
        last = 0
        for start, end in spans:
            payload = full[start:end]
            stage = Match(payload, 0, len(payload), [])
            sub = _transform(rest, payload, (*ancestors, stage), committed=True)
            if sub is None:
                return None
            pieces.append(full[last:start])
            pieces.append(sub)
            last = end
        pieces.append(full[last:])
        return "".join(pieces)

    pieces: list[str] = []
    last = 0
    matched = False
    for m in find_matches(head, text, ancestors):
        matched = True
        sub = _transform(rest, m.text, (*ancestors, m), committed)
        if sub is None:
            return None
        pieces.append(text[last : m.start])
        pieces.append(sub)
        last = m.end
    if not matched:
        return text if committed else None
    pieces.append(text[last:])
    return "".join(pieces)


def deltas(
    steps: list[Step], target: str, stop: int | None = None
) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each surviving first-query match's
    source span and its transformed result. `execute` lists the texts; `splice`
    lays them back over the source. `stop` caps where a branch may begin (used by
    `splice_to_fixed_point` to skip the already-settled tail)."""
    if not steps:
        return []
    head = steps[0]
    if isinstance(head, Template):
        # A leading template has no query to locate matches: the whole document is
        # one branch, with `{{.}}` the entire input. Render the chain over it.
        text = _transform(steps, target, ())
        return [] if text is None else [(0, len(target), text)]
    rest = steps[1:]
    result: list[tuple[int, int, str]] = []
    for m in find_matches(head, target, stop=stop):
        text = _transform(rest, m.text, (m,))
        if text is not None:
            result.append((m.start, m.end, text))
    return result


# ── Renderings ────────────────────────────────────────────────────────────────


def execute(steps: list[Step], target: str) -> list[str]:
    """The list of rendered matches — one entry per surviving leaf branch."""
    return [text for _, _, text in deltas(steps, target)]


def splice(steps: list[Step], target: str) -> str:
    """The source with each leaf branch's span replaced by its render, the text
    between branches kept verbatim (in-place transform)."""
    out: list[str] = []
    last = 0
    for start, end, text in deltas(steps, target):
        out.append(target[last:start])
        out.append(text)
        last = end
    out.append(target[last:])
    return "".join(out)


# ── Pipelines ─────────────────────────────────────────────────────────────────


def splice_to_fixed_point(steps: list[Step], target: str) -> str:
    """Re-splice `steps` over `target` until a pass changes nothing (the fixed
    point) — the in-place form of a `while` loop, for a `<=` statement. A
    contracting rule settles in a few passes per unit of input, so the guards only
    trip on a rule that does not converge (a `CompileError`): a pass count (catches
    oscillators) and a size bound (catches a grower like `{a} <= "aa"`).

    Incremental (safe but not a left-skip): each pass remembers where its last
    change ended and the next pass only *begins* matches before that point.
    Matching reads forward, so a match that differs this pass must read a byte the
    last pass rewrote — and one can begin no later than the last such byte.
    Everything beyond it is byte-identical to a tail the previous pass already
    scanned and found settled, so re-scanning it for new starts is waste. The dual
    (skipping the *prefix* before the first change) is **unsafe**: a forward-reading
    rule can begin a match before the change and read into it (bubble_sort mis-sorts
    `2,3,1` that way), so only the tail is pruned. The win grows with input size —
    near 1× on a small input, but ~1.4-1.6× on the full dedup file as the tail the
    fixed point has settled grows over its many passes. It is backend-agnostic (the
    native backend honours the same `stop` bound)."""
    text = target
    cap = 8 * len(target) + 1024
    size_limit = 64 * len(target) + 65536
    stop = None  # the first pass scans the whole document
    for _ in range(cap):
        out: list[str] = []
        last = 0
        length = 0  # running length of `out` == offset into the new document
        dirty: int | None = None  # end (new coords) of the right-most real change
        for s, e, repl in deltas(steps, text, stop=stop):
            out.append(text[last:s])
            out.append(repl)
            length += (s - last) + len(repl)
            if repl != text[s:e]:  # an identity rewrite changes nothing, so skip it
                dirty = length
            last = e
        if dirty is None:
            return text  # nothing changed — the fixed point
        out.append(text[last:])
        text = "".join(out)
        stop = dirty  # next pass: no new match can begin past the last change
        if len(text) > size_limit:
            break
    raise CompileError(
        "a `<=` statement did not settle: the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


def run_pipeline(pipeline: list[list[Step]], target: str) -> str:
    """Run a pipeline of statements over `target`, each spliced in turn, returning
    the transformed document. A `<=` (fixed-point) statement — flagged on its first
    step — is re-spliced until the text stops changing (`splice_to_fixed_point`)."""
    text = target
    for steps in pipeline:
        if steps and steps[0].fixed_point:
            text = splice_to_fixed_point(steps, text)
        else:
            text = splice(steps, text)
    return text


# ── Script compilation ────────────────────────────────────────────────────────


def _split_fixed_point(statement: str) -> tuple[str, bool]:
    """Rewrite each top-level `<=>` arrow to `=>`, returning `(text, used_<=>)`."""
    out: list[str] = []
    depth = 0
    inq = False
    found = False
    i = 0
    n = len(statement)
    while i < n:
        ch = statement[i]
        if ch == "\\" and i + 1 < n:
            out.append(statement[i : i + 2])
            i += 2
            continue
        if ch == '"':
            inq = not inq
        elif inq:
            pass
        elif ch == "<" and statement[i + 1 : i + 3] == "=>" and depth == 0:
            out.append("=>")
            found = True
            i += 3
            continue
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        out.append(ch)
        i += 1
    return "".join(out), found


_DEFINITION_RE = None  # compiled lazily


def _split_definition(item: str) -> tuple[str, str] | None:
    """A script definition `@name = body` -> `(name, body)`; None otherwise."""
    import re
    global _DEFINITION_RE
    if _DEFINITION_RE is None:
        _DEFINITION_RE = re.compile(r"\s*@(\w+)\s*")
    m = _DEFINITION_RE.match(item)
    if m is None:
        return None
    rest = item[m.end() :]
    if rest.startswith("=") and not rest.startswith("=>"):
        return m.group(1), rest[1:].strip()
    return None


def _logical_lines(text: str) -> list[str]:
    """Split on newlines at brace/quote depth 0."""
    lines: list[str] = []
    buf: list[str] = []
    depth = 0
    inq = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            buf.append(text[i : i + 2])
            i += 2
            continue
        if depth == 0 and not inq and c == "/" and text[i + 1 : i + 2] == "/":
            j = text.find("\n", i)
            end = n if j == -1 else j
            buf.append(text[i:end])
            i = end
            continue
        if c == "\n" and depth == 0 and not inq:
            lines.append("".join(buf))
            buf = []
        elif c == '"':
            inq = not inq
            buf.append(c)
        else:
            if not inq:
                depth += (c == "{") - (c == "}")
            buf.append(c)
        i += 1
    lines.append("".join(buf))
    return lines


def _strip_comment(line: str) -> str:
    """Remove a `//` line comment, respecting braces and quotes."""
    depth = 0
    inq = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif not inq:
            if c == "/" and depth == 0 and line[i + 1 : i + 2] == "/":
                return line[:i]
            depth += (c == "{") - (c == "}")
        i += 1
    return line


def split_statements(text: str) -> list[str]:
    """Split `.hmk` source into statement strings."""
    statements: list[str] = []
    current: list[str] = []
    for raw in _logical_lines(text):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("=>"):
            current.append(line)
        else:
            if current:
                statements.append("\n".join(current))
            current = [line]
    if current:
        statements.append("\n".join(current))
    return statements


def compile_script(source: str) -> list[list[Step]]:
    """Compile a `.hmk` script that may carry local `@name = <body>` definitions
    into a runnable pipeline."""
    from himark.models.exceptions import CompileError

    local: dict[str, str] = {}
    pipeline: list[list[Step]] = []
    for item in split_statements(source):
        if (defn := _split_definition(item)) is not None:
            name, body = defn
            if name in VARIABLES:
                raise CompileError(f"definition @{name} shadows a prelude variable")
            if name in local:
                raise CompileError(f"@{name} is already defined")
            local[name] = body
            continue
        converted, loop = _split_fixed_point(item)
        steps = parser.parse(converted, variables=local)
        if loop and steps:
            steps[0].fixed_point = True
        pipeline.append(steps)
    return pipeline


def load_script(path: str) -> list[list[Step]]:
    """Read and compile a `.hmk` script file into a runnable pipeline."""
    from pathlib import Path
    return compile_script(Path(path).read_text("utf-8"))


def compile_pipeline(statements: list[str]) -> list[list[Step]]:
    """Parse and compile raw HMK statements into a runnable pipeline."""
    pipeline: list[list[Step]] = []
    for s in statements:
        converted, loop = _split_fixed_point(s)
        steps = parser.parse(converted)
        if loop and steps:
            steps[0].fixed_point = True
        pipeline.append(steps)
    return pipeline
