from himark.models import nodes_typed as t
from himark.parser import phase0, phase1, phase2, phase3


def parse(text: str, macros: dict[str, str] | None = None) -> list[t.RootNode]:
    """Run all phases and return one tree per => step.

    Single-step pattern  => [pattern_tree]
    Pattern + template   => [pattern_tree, template_tree]
    Chained              => [p1_tree, p2_tree, ..., template_tree]

    `macros` overlays the prelude with script-local `@name` definitions, expanded
    in phase 1 (see `tools/precompiled.compile_script`).
    """
    steps = phase0.split_statement(text)
    return [
        phase3.parse(phase2.parse(phase1.preprocess(step, macros=macros)))
        for step in steps
    ]
