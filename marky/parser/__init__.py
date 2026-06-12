from marky.models import nodes_typed as t
from marky.parser import phase0, phase1, phase2, phase3


def parse(text: str) -> list[t.RootNode]:
    """Run all phases and return one tree per => step.

    Single-step pattern  => [pattern_tree]
    Pattern + template   => [pattern_tree, template_tree]
    Chained              => [p1_tree, p2_tree, ..., template_tree]
    """
    return [
        phase3.parse(phase2.parse(phase0.preprocess(step)))
        for step in phase1.split_statement(text)
    ]
