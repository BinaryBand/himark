"""Tests for the symbol-resolver registry (marky/utils/resolver.py)."""

from marky import parser
from marky.engine import execute
from marky.utils.resolver import RESOLVERS, register


def run(hmk: str, target: str) -> list[str]:
    return execute(parser.parse(hmk), target)


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------


def test_emoji_resolver_pre_registered():
    assert "emoji" in RESOLVERS


def test_latex_resolver_pre_registered():
    assert "latex" in RESOLVERS


def test_registered_resolvers_are_callable():
    for name, resolver in RESOLVERS.items():
        assert callable(resolver), f"RESOLVERS[{name!r}] is not callable"


# ---------------------------------------------------------------------------
# Custom resolver: registration and end-to-end rendering
# ---------------------------------------------------------------------------


def test_custom_resolver_registers_and_resolves():
    register("_test_star", lambda content: f"*{content}*")
    try:
        assert "_test_star" in RESOLVERS
        assert RESOLVERS["_test_star"]("foo") == "*foo*"
    finally:
        del RESOLVERS["_test_star"]


def test_resolver_end_to_end_via_engine():
    """A newly registered resolver is picked up by render without engine changes."""
    original = RESOLVERS["emoji"]
    register("emoji", lambda content: f"<{content}>")
    try:
        assert run("{x} => {{ :tada: }}", "x") == ["<tada>"]
    finally:
        RESOLVERS["emoji"] = original


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


def test_unknown_emoji_shortcode_returns_colon_wrapped():
    result = run("{x} => {{ :definitely_not_a_real_emoji_xyz: }}", "x")
    assert result == [":definitely_not_a_real_emoji_xyz:"]


def test_unknown_latex_expr_returns_dollar_wrapped():
    result = run("{x} => {{ $\\undefinedcmd$ }}", "x")
    assert result == ["$\\undefinedcmd$"]
