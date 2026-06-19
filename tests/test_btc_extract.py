"""End-to-end tests for the Bitcoin-address extractor (`himark/scripts/btc_extract.hmk`).

The script tags every legacy P2PKH (`1…`) address in a document with
`<btc>…</btc>` and leaves everything else verbatim. These tests pin that
behaviour on small inputs, then stress it on a long synthetic document of base58
noise with real addresses planted throughout (the efficiency target).
"""

import random
import re
import time
from pathlib import Path

import pytest

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[1] / "himark" / "scripts" / "btc_extract.hmk"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))

# A few real legacy mainnet addresses (the Genesis coinbase and two vanity ones).
ADDRS = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


def tagged(text: str) -> list[str]:
    return re.findall(r"<btc>(.*?)</btc>", run(text))


def test_tags_a_single_address():
    assert run(" pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa now") == (
        " pay <btc>1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa</btc> now"
    )


def test_tags_every_address_in_a_line():
    text = " " + " ".join(ADDRS)
    assert tagged(text) == ADDRS


def test_skips_p2sh_address():
    # A `3…` P2SH address has an interior `1`, but the boundary anchor keeps it
    # from being read as the start of a P2PKH address.
    assert tagged(" send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here") == []


def test_skips_plain_base58_noise():
    # Base58 words that are not `1`-led, address-length, in-range values.
    assert tagged(" zzzzQ9xWvTpLmNkJhGfDsAbCeRtYuIo 2short 99 abcDEF") == []


def test_non_address_text_is_preserved_verbatim():
    text = " a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b 12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX c\n"
    restored = run(text).replace("<btc>", "").replace("</btc>", "")
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
        kind = rng.random()
        if kind < 0.15:  # `1`-led but too short to be an address (rejected in-bound)
            parts.append("1" + "".join(rng.choice(B58) for _ in range(rng.randint(3, 20))))
        else:  # not `1`-led; varied lengths, including address-length runs
            head = rng.choice("23456789")
            parts.append(head + "".join(rng.choice(B58) for _ in range(rng.randint(3, 49))))
        if i % 400 == 200:
            a = ADDRS[i % len(ADDRS)]
            parts.append(a)
            planted.append(a)
    return " " + " ".join(parts) + " ", planted


def test_stress_extracts_all_planted_addresses_quickly():
    target, planted = _stress_target()
    assert len(target) > 100_000  # a genuinely long document
    t0 = time.perf_counter()
    out = run(target)
    elapsed = time.perf_counter() - t0
    found = re.findall(r"<btc>(.*?)</btc>", out)
    # Every planted address is found, in order, with no false positives.
    assert found == planted
    # The transform is lossless apart from the tags.
    assert out.replace("<btc>", "").replace("</btc>", "") == target
    # Generous time bound — a catastrophic-regression guard, not a benchmark.
    assert elapsed < 10.0, f"extraction took {elapsed:.2f}s for {len(target):,} chars"
