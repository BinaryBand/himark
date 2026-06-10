"""Tests for the SymbolResolver Protocol and central registry (marky/utils/resolver.py)."""

from marky import parser
from marky.engine import execute
from marky.utils.resolver import RESOLVERS, SymbolResolver, register


def run(hmk: str, target: str) -> list[str]:
    return execute(parser.parse(hmk), target)


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------


def test_emoji_resolver_pre_registered():
    assert "emoji" in RESOLVERS


def test_latex_resolver_pre_registered():
    assert "latex" in RESOLVERS


def test_emoji_metadata_key():
    assert RESOLVERS["emoji"].metadata_key == "code"


def test_latex_metadata_key():
    assert RESOLVERS["latex"].metadata_key == "expr"


# ---------------------------------------------------------------------------
# Protocol compliance (runtime_checkable)
# ---------------------------------------------------------------------------


def test_registered_resolvers_satisfy_protocol():
    for name, resolver in RESOLVERS.items():
        assert isinstance(resolver, SymbolResolver), (
            f"RESOLVERS[{name!r}] does not satisfy SymbolResolver Protocol"
        )


def test_object_missing_resolve_does_not_satisfy_protocol():
    class _Bad:
        node_type = "x"
        metadata_key = "y"

    assert not isinstance(_Bad(), SymbolResolver)


def test_object_missing_metadata_key_does_not_satisfy_protocol():
    class _Bad:
        node_type = "x"

        def resolve(self, content: str) -> str:
            return content

    assert not isinstance(_Bad(), SymbolResolver)


# ---------------------------------------------------------------------------
# Custom resolver: registration and end-to-end rendering
# ---------------------------------------------------------------------------


class _BracketResolver:
    node_type = "emoji"  # will be temporarily replaced below
    metadata_key = "code"

    def resolve(self, content: str) -> str:
        return f"[{content}]"


def test_custom_resolver_registers_and_resolves(monkeypatch):
    class _StarResolver:
        node_type = "_test_star"
        metadata_key = "code"

        def resolve(self, content: str) -> str:
            return f"*{content}*"

    resolver = _StarResolver()
    register(resolver)
    try:
        assert "_test_star" in RESOLVERS
        assert RESOLVERS["_test_star"].resolve("foo") == "*foo*"
    finally:
        del RESOLVERS["_test_star"]


def test_resolver_end_to_end_via_engine(monkeypatch):
    """A newly registered resolver is picked up by _render without engine changes."""

    class _TagResolver:
        node_type = "emoji"
        metadata_key = "code"

        def resolve(self, content: str) -> str:
            return f"<{content}>"

    original = RESOLVERS["emoji"]
    RESOLVERS["emoji"] = _TagResolver()
    try:
        result = run("[x] => {{ :tada: }}", "x")
        assert result == ["<tada>"]
    finally:
        RESOLVERS["emoji"] = original


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


def test_unknown_emoji_shortcode_returns_colon_wrapped():
    result = run("[x] => {{ :definitely_not_a_real_emoji_xyz: }}", "x")
    assert result == [":definitely_not_a_real_emoji_xyz:"]


def test_unknown_latex_expr_returns_dollar_wrapped():
    result = run("[x] => {{ $\\undefinedcmd$ }}", "x")
    assert result == ["$\\undefinedcmd$"]
