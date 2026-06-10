from marky import parser
from marky.engine import execute


def run_and_print(pat, target):
    print("pattern:", pat)
    trees = parser.parse(pat)
    print("parsed trees:", trees)
    print("execute ->", execute(trees, target))


if __name__ == "__main__":
    run_and_print("\\[[a]\\]", "[x]")
