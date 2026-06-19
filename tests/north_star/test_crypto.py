"""North Star: Cryptocurrency address patterns."""

import pytest

from himark import parser
from himark.engine import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── Bitcoin P2PKH ─────────────────────────────────────────────────────────────
# A leading '1' then a base58 value bounded by the smallest and largest 25-byte
# addresses (the floor/ceiling widths give the length window).

BTC = "{1}{111111111111111111111111:@b58:2n1XR4oJkmBdJMxhBGQGb96gQ88xUzxLFyG}"


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


# ── Control vectors: real mainnet P2PKH addresses (varying lengths) ───────────
# Every one of these is a genuine, well-formed legacy address and must match in
# full. They span the realistic length range (27–34 chars), so they exercise the
# floor/ceiling width window end to end.

VALID_BTC = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi genesis coinbase
    "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1HLoD9E4SDFFPDiYfNYnkBLQ85Y51J3Zb1",
    "1FvzCLoTPGANNjWoUo6jUGuAG3wg1w4YjR",
    "16ftSEQ4ctQFDtVZiUBusQUjRrGhM3JYwe",
    "1QLbz7JHiBTspS962RLKV8GndWFwi5j6Qr",
    "1111111111111111111114oLvT2",  # the all-but-burn short address (27 chars)
]


@pytest.mark.parametrize("addr", VALID_BTC)
def test_btc_control_valid_matches_whole(addr):
    assert addr in matches(BTC, addr)


# Control non-addresses. The whole string must never be returned as a match.
# (HMK is anchorless, so an inner '1…' sub-run may still match — that is fine;
# we only assert the *entire* string is rejected.)

INVALID_BTC = [
    "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",  # P2SH (version byte 3)
    "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",  # bech32 segwit
    "A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # missing the leading '1'
    "1abcd",  # far too short
]


@pytest.mark.parametrize("addr", INVALID_BTC)
def test_btc_control_invalid_not_whole(addr):
    assert addr not in matches(BTC, addr)


def test_btc_rejects_forbidden_base58_symbols():
    # base58 excludes 0, O, I, and l. A run made of a forbidden symbol must not
    # match — the alphabet's exclusions apply inside a value-bounded field, not
    # only to a single-position class.
    assert matches(BTC, "1" + "O" * 33) == []
    assert matches(BTC, "1" + "0" * 33) == []
    # A legitimate address is still found after a forbidden-symbol prefix.
    addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7D"
    assert addr in matches(BTC, "1O0Il" + addr)


# ── Ethereum ──────────────────────────────────────────────────────────────────
# 0x prefix + exactly 40 hex digits. A fixed width is a floor and ceiling written
# at the same width, so the value runs from 40 zeros to 40 f's (case-folded).

ETH = "{0x}{" + "0" * 40 + ":@hex:" + "f" * 40 + "}"


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
