"""End-to-end tests for the Bitcoin-address extractor (`himark/scripts/btc_extract.hmk`).

The script rewrites every legacy P2PKH (`1…`) address as
`<btc addr="…" expect=<hex> actual=<hex>/>`, where `actual` is the checksum
carried in the address and `expect` is the checksum recomputed from its body —
equal for a real address, different for a base58 look-alike. These tests pin that
behaviour on small inputs, then stress it on a long synthetic document of base58
noise with real addresses planted throughout (the efficiency target).
"""

import hashlib
import random
import re
import time
from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[1] / "himark" / "scripts" / "btc_extract.hmk"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))

# Real legacy mainnet addresses (the Genesis coinbase and two vanity ones).
ADDRS = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TAG = re.compile(r'<btc addr="([^"]+)" expect=([0-9a-f]+) actual=([0-9a-f]+)/>')


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


def hits(text: str):
    """(address, expect, actual) for every tagged address in `text`."""
    return _TAG.findall(run(text))


def addresses(text: str) -> list[str]:
    return [a for a, _, _ in hits(text)]


def test_tags_a_single_address_with_matching_checksum():
    [(addr, expect, actual)] = hits(" pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa now")
    assert addr == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    assert expect == actual  # a real address: recomputed == embedded


def test_expect_matches_independent_base58check():
    # The script's `expect` equals a from-scratch base58check checksum.
    addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    value = 0
    for c in addr:
        value = value * 58 + B58.index(c)
    payload = value.to_bytes(25, "big")
    want = hashlib.sha256(hashlib.sha256(payload[:21]).digest()).digest()[:4].hex()
    [(_, expect, actual)] = hits(" " + addr)
    assert expect == want
    assert actual == payload[21:].hex()


def test_tags_every_address_in_a_line():
    assert addresses(" " + " ".join(ADDRS)) == ADDRS


def test_all_real_addresses_have_valid_checksums():
    for a, expect, actual in hits(" " + " ".join(ADDRS)):
        assert expect == actual, f"{a} should be valid"


def test_skips_p2sh_address():
    # A `3…` P2SH address has an interior `1`, but the boundary anchor keeps it
    # from being read as the start of a P2PKH address.
    assert hits(" send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here") == []


def test_flags_a_lookalike_as_invalid():
    # A `1`-led base58 word of address shape but no valid checksum still matches
    # (the engine cannot run base58check in matching position), but expect/actual
    # disagree, so it is filterable.
    addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfXX"  # genesis with the tail mangled
    found = hits(" " + addr)
    if found:  # it is shape-valid, so it matches
        [(a, expect, actual)] = found
        assert a == addr
        assert expect != actual  # …but the checksum exposes it


def test_non_address_text_is_preserved_verbatim():
    text = " a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b end\n"
    restored = _TAG.sub(lambda m: m.group(1), run(text))
    assert restored == text


def _stress_target(seed: int = 0):
    """A long document: base58 noise tokens with real addresses planted in it.

    Noise is never a `1`-led address-shaped value, so the only matches are the
    planted addresses. `1`-led short tokens are included so the value matcher is
    entered and cleanly rejected (width below the floor), not just skipped."""
    rng = random.Random(seed)
    parts: list[str] = []
    planted: list[str] = []
    for i in range(8000):
        if rng.random() < 0.15:  # `1`-led but too short to be an address
            parts.append("1" + "".join(rng.choice(B58) for _ in range(rng.randint(3, 20))))
        else:  # not `1`-led; varied lengths, including address-length runs
            head = rng.choice("23456789")
            parts.append(head + "".join(rng.choice(B58) for _ in range(rng.randint(3, 49))))
        if i % 400 == 200:
            a = ADDRS[i % len(ADDRS)]
            parts.append(a)
            planted.append(a)
    return " " + " ".join(parts) + " ", planted


def test_stress_extracts_and_validates_all_planted_addresses_quickly():
    target, planted = _stress_target()
    assert len(target) > 100_000  # a genuinely long document
    t0 = time.perf_counter()
    out = run(target)
    elapsed = time.perf_counter() - t0
    found = _TAG.findall(out)
    # Every planted address is found, in order, and validates (expect == actual).
    assert [a for a, _, _ in found] == planted
    assert all(expect == actual for _, expect, actual in found)
    # Lossless apart from the tags.
    assert _TAG.sub(lambda m: m.group(1), out) == target
    # Generous time bound — a catastrophic-regression guard, not a benchmark.
    assert elapsed < 10.0, f"extraction took {elapsed:.2f}s for {len(target):,} chars"
