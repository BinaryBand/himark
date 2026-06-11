from marky.models.node import HMKNode
from marky.parser import phase0, phase1, phase2, phase3


def parse(text: str) -> list[HMKNode]:
    """Run all phases and return one tree per => step.

    Single-step pattern  => [pattern_tree]
    Pattern + template   => [pattern_tree, template_tree]
    Chained              => [p1_tree, p2_tree, ..., template_tree]
    """
    stmt = phase1.split_statement(text)
    return [phase3.parse(phase2.parse(phase0.preprocess(step))) for step in stmt.steps]
