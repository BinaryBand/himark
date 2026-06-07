test_cases = [
    "[a]",
    "[abc]",
    "[a||c]",
    "[hello||world]",
    "[hello][ ..][world]",
    "[a..z][.][a..z]",
    "[a..z]",
    "[A..Z]",
    "[a..Z]",
    "[a..c||H]",
    "[a..c||F..H]",
    "[..]",
    "[0..]",
    "[a..]",
    "[ ..]",
    "[5..99]",
    "[0..9](b10)",
    "[0..f](hex)",
    "[0..v](b32)",
    "[1..z](b58)",
    "[A../](b64)",
    "[hello](i)",
    "[0..99]",
    "[0..ff](hex)",
    "[0..99](pad:2)",
    "[0..ff](hex, pad:2)",
    "[f..fff](hex, pad:4)",
    "[[a]]",
    "[[a..z]]",
    "[[abc]]",
    "[[hello||world]]",
    "[a](1..3)",
    "<<foo>>"
]


def main():
    import re

    parenthesis = r"\(([^)]+)\)"
    single_brackets = r"\[([^\]]+)\]"
    double_brackets = r"\[\[([^\]]+)\]\]"
    brackets = f"{double_brackets}|{single_brackets}"
    brackets_with_opts = f"{brackets}(?:{parenthesis})?"

    double_chevrons = r"<<((?:[^>]|>[^>])*)>>"

    possible_matches = f"{brackets_with_opts}|{double_chevrons}"

    for test in test_cases:
        match = re.match(possible_matches, test)
        if match:
            print(f"Matched: {test}")
            print(f"  Double Brackets: {match.group(1)}")
            print(f"  Single Brackets: {match.group(2)}")
            print(f"  Bracket Options: {match.group(3)}")
            print(f"  Double Chevrons: {match.group(4)}")
            print(f"  Remaining Text: {test[match.end():]}")
        else:
            print(f"No match: {test}")


if __name__ == "__main__":
    main()