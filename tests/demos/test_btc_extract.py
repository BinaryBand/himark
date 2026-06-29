"""End-to-end tests for the Bitcoin-address extractor (`himark/scripts/btc_extract.hmk`).

The script is a *structural* (layer-1) extractor: every base58 run shaped like a
25-byte P2PKH address (a `1` version byte plus a value in the address range)
becomes `<btc>1A1zP1eP…</btc>`; other text is left untouched. It does **not**
validate the checksum — that is a double SHA-256, deferred to a layer above the
byte primitives — so an address-shaped word with a bad checksum is tagged too.
These tests pin the shape match on small inputs, then stress it on a long
synthetic document of base58 noise with real addresses planted in it.
"""

import random
import re
import time
from pathlib import Path

from himark import engine, parser

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "btc_extract.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = parser.load_script(str(SCRIPT))

# Real legacy mainnet addresses (the Genesis coinbase and two vanity ones).
ADDRS = [
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
]
# Genesis with the final base58 digit changed: address-shaped, bad checksum.
LOOKALIKE = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TAG = re.compile(r"<btc>([^<]+)</btc>")


def run(text: str) -> str:
    return engine.run_pipeline(_PIPELINE, text)


def tagged(text: str) -> list[str]:
    """The address-shaped runs the pipeline tagged (wrapped in <btc>…</btc>)."""
    return _TAG.findall(run(text))


def test_real_addresses_are_kept():
    assert tagged(" pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa now") == [ADDRS[0]]


def test_tags_every_address_shaped_run_in_a_line():
    assert tagged(" " + " ".join(ADDRS)) == ADDRS


def test_lookalike_is_tagged_too_checksum_is_layer_2():
    # A structural match cannot tell a bad checksum from a good one — the
    # address-shaped lookalike is tagged like any other. (Filtering it out is the
    # job of the deferred base58check, not this layer-1 pass.)
    assert tagged(" send " + LOOKALIKE + " here") == [LOOKALIKE]


def test_tags_all_address_shaped_runs_mixed():
    out = run(" a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b " + LOOKALIKE + " c")
    assert out == (
        " a <btc>1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa</btc> b "
        "<btc>" + LOOKALIKE + "</btc> c"
    )


def test_skips_p2sh_address():
    # A `3…` P2SH address has an interior `1`, but the boundary anchor keeps it
    # from being read as the start of a P2PKH address.
    assert run(" send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here") == (
        " send 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy here"
    )


def test_non_address_text_is_preserved():
    text = " a 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa b end\n"
    assert _TAG.sub(lambda m: m.group(1), run(text)) == text


def _stress_target(seed: int = 0):
    """A long document: base58 noise with real addresses planted throughout.

    Noise is never a `1`-led address-shaped value, so the planted addresses are
    the only matches. `1`-led short tokens are included so the value matcher is
    entered and cleanly rejected (width below the floor), not merely skipped."""
    rng = random.Random(seed)
    parts: list[str] = []
    planted: list[str] = []
    for i in range(8000):
        if rng.random() < 0.15:  # `1`-led but too short to be an address
            parts.append(
                "1" + "".join(rng.choice(B58) for _ in range(rng.randint(3, 20)))
            )
        else:  # not `1`-led; varied lengths, including address-length runs
            head = rng.choice("23456789")
            parts.append(
                head + "".join(rng.choice(B58) for _ in range(rng.randint(3, 49)))
            )
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
    # Every planted (address-shaped) run is tagged, in order; the noise is never
    # `1`-led address-shaped, so there are no false positives.
    assert _TAG.findall(out) == planted
    # Lossless apart from the tags.
    assert _TAG.sub(lambda m: m.group(1), out) == target
    # Generous time bound — a catastrophic-regression guard, not a benchmark.
    assert elapsed < 15.0, f"extraction took {elapsed:.2f}s for {len(target):,} chars"


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to apply the shipped script to a real input file and
# write the result to `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    text = (RESOURCES / "addresses.txt").read_text("utf-8")
    out = run(text)
    (OUTPUT / "addresses_out.txt").write_text(out, "utf-8")
    print(f"Wrote addresses_out.txt to {OUTPUT}")
