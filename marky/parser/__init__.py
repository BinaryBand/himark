from marky.models import nodes_typed as t
from marky.parser import phase0, phase1, phase2, phase3


def parse(text: str) -> list[t.RootNode]:
    """Run all phases and return one tree per => step.

    Single-step pattern  => [pattern_tree]
    Pattern + template   => [pattern_tree, template_tree]
    Chained              => [p1_tree, p2_tree, ..., template_tree]

    The statement's replace-mode flag (`=>+`) rides on the first tree's
    `replace` attribute, where `execute` reads it.
    """
    steps, replace = phase0.split_statement(text)
    trees = [
        phase3.parse(phase2.parse(phase1.preprocess(step, first=i == 0)))
        for i, step in enumerate(steps)
    ]
    if trees:
        trees[0].replace = replace
    return trees
