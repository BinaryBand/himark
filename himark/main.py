from himark import parser
from himark.node import print_tree

test_cases = {
    "Basic literals": [
        "[a]",
        "[abc]",
        "[a||c]",
        "[hello||world]",
    ],
    "Multi-token sequences": [
        "[hello][ ..][world]",
        "[a..z][.][a..z]",
    ],
    "Ranges": [
        "[a..z]",
        "[A..Z]",
        "[a..Z]",
        "[a..c||H]",
        "[a..c||F..H]",
        "[A..z]",
    ],
    "Shortcuts": [
        "[..]",
        "[0..]",
        "[a..]",
        "[ ..]",
    ],
    "Integer value ranges": [
        "[5..99]",
        "[0..99]",
    ],
    "Alternate alphabets": [
        "[0..9](b10)",
        "[0..f](hex)",
        "[0..v](b32)",
        "[1..z](b58)",
        "[A../](b64)",
        "[hello](i)",
    ],
    "Padded ranges": [
        "[0..ff](hex)",
        "[0..99](pad:2)",
        "[0..ff](hex, pad:2)",
        "[f..fff](hex, pad:4)",
    ],
    "Negation": [
        "[[a]]",
        "[[a..z]]",
        "[[abc]]",
        "[[hello||world]]",
        "[[a||b||c]]",
    ],
    "Repetition": [
        "[a]",
        "[a](2)",
        "[a](1..)",
        "[a](0..)",
        "[a](1..3)",
        "[a](..3)",
        "[a||b](2)",
        "[a](0.., ?)",
    ],
    "Varied repetition": [
        "[a](n)[b](n)",
        "[a](2..n)[b](n..3)",
        "[a](n)[b](n)[c](m)[d](m)",
    ],
    "Escapes": [
        r"[\[]",
        r"[\]]",
        r"[\\]",
        r"[\t]",
        r"[\n]",
        r"[\r]",
    ],
    "Anchors": [
        "^[a..z]",
        "[a..z]$",
        "^^[a..z]$$",
    ],
    "Separators": [
        "<</>>",
        "<<foo>>",
        "[W<</>>Ex]",
        "[W]<</>>[Ex]",
    ],
    "Template variables": [
        "{{ . }}",
        "{{ 1 }}",
        "{{ 1.2 }}",
        "{{ 1.2..3.1 }}",
        "{{ :tada: }}",
        "{{ $\\pi$ }}",
        "{{ n }}",
    ],
    "Transformer statements": [
        "[selector] => <template>{{ . }}</template>",
        "^<<#>>$ => <h1>{{ . }}</h1>",
        "[a..z](n) => <b>{{ . }}</b>",
        "[done] => {{ . }} {{ :tada: }}",
        "[0..][px||em||rem] => {{ 1 }}",
    ],
}


def main():
    print("=" * 70)
    print("HMK Parser - Three Phase Output")
    print("=" * 70)

    for group, cases in test_cases.items():
        print(f"\n--- {group} ---\n")
        for text in cases:
            print(f"Input: {text!r}")
            pattern_tree, template_tree = parser.parse(text)
            print_tree(pattern_tree)
            if template_tree:
                print("  => (template)")
                print_tree(template_tree, indent=1)
            print()


if __name__ == "__main__":
    main()
