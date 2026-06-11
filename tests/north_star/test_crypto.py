"""North Star: Cryptocurrency address patterns."""

from marky import parser
from marky.engine._match import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── Bitcoin P2PKH ─────────────────────────────────────────────────────────────
# Matches a leading '1' then a b58 body bounded to the P2PKH value range.

BTC = "{1}{11111111111111111111111..{@b58}..zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz}"

# The same pattern written with singleton constructors instead of literal runs.
BTC_SINGLETON = "{1}{{1}[23]..{@b58}..{z}[33]}"


def test_btc_singleton_form_is_equivalent():
    addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    assert matches(BTC, addr) == matches(BTC_SINGLETON, addr)


def test_btc_genesis_address():
    assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in matches(
        BTC, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    )


def test_btc_p2sh_not_matched_whole():
    # P2SH addresses start with '3'; the full address is never a P2PKH match.
    # HMK has no anchors so the engine may still find sub-matches at an inner '1'.
    assert "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy" not in matches(
        BTC, "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
    )


def test_btc_extracted_from_prose():
    assert "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2" in matches(
        BTC, "send to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 or hold"
    )


def test_btc_leading_one_required():
    assert "A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" not in matches(
        BTC, "A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    )


# ── Ethereum ──────────────────────────────────────────────────────────────────
# 0x prefix + exactly 40 hex digits (case-insensitive).
# {0..9,a..f,A..F} is a char union; {40: ...} enforces the fixed width.

ETH = "{0x}{40: {0..9,a..f,A..F}}"


def test_eth_valid_address():
    addr = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
    assert addr in matches(ETH, addr)


def test_eth_all_lowercase():
    addr = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
    assert addr in matches(ETH, addr)


def test_eth_all_uppercase():
    addr = "0xDE0B295669A9FD93D5F28D9EC85E40F4CB697BAE"
    assert addr in matches(ETH, addr)


def test_eth_wrong_prefix_not_matched():
    assert "742d35Cc6634C0532925a3b844Bc454e4438f44e" not in matches(
        ETH, "742d35Cc6634C0532925a3b844Bc454e4438f44e"
    )


def test_eth_too_short_not_matched():
    # Only 39 hex digits after 0x — should not be a full match.
    short = "0x742d35Cc6634C0532925a3b844Bc454e4438f4"
    assert short not in matches(ETH, short)


def test_eth_extracted_from_prose():
    addr = "0xAb8483F64d9C6d1EcF9b849Ae677dD3315835cb2"
    text = f"transfer to {addr} now"
    assert addr in matches(ETH, text)
