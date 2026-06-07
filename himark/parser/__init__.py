from himark.parser import phase1, phase2, phase3
from himark.node import HMKNode


def parse(text: str) -> list[HMKNode]:
    """Run all three phases and return one tree per => step.

    Single-step pattern  => [pattern_tree]
    Pattern + template   => [pattern_tree, template_tree]
    Chained              => [p1_tree, p2_tree, ..., template_tree]
    """
    stmt = phase1.split_statement(text)
    return [phase3.parse(phase2.parse(step)) for step in stmt.steps]
