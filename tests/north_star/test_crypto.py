"""North Star: Cryptocurrency address patterns."""

from marky import parser
from marky.engine._match import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── Bitcoin P2PKH ─────────────────────────────────────────────────────────────
# Matches a leading '1' then a width-bounded b58 body. Length is a width
# constraint, not a value constraint — '1' is b58's zero symbol, so a value
# lower bound cannot enforce a minimum length.

BTC = "{1}{24..33:{@b58}}"


def test_btc_minimum_length_enforced():
    # A short b58 run after the '1' prefix is not an address.
    assert matches(BTC, "1abcd") == []


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
# 0x prefix + exactly 40 hex digits (case-insensitive). The doc form: a
# membership-only union (duplicate digits are harmless without a value bound)
# width-fixed to 40.

ETH = "{0x}{40:{@hex,@HEX}}"


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
