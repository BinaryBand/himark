from himark import parser
from himark.parser import phase2


def dump(node, indent=0):
    print('  ' * indent + f"{node.type}: {node.content!r} meta={node.metadata}")
    for c in node.children:
        dump(c, indent + 1)


if __name__ == '__main__':
    print('--- phase2 tree ---')
    p2 = phase2.parse('[0..ff](hex, pad:2)')
    dump(p2)
    print('\n--- phase3 (via parser.parse) ---')
    try:
        patterns = [
            '[0..ff](hex, pad:2)',
            '\\[[a]\\]',
            '[\\n]',
        ]
        for pat in patterns:
            print('\n=== pattern:', pat)
            try:
                p2 = phase2.parse(pat)
                dump(p2)
            except Exception as e:
                print('phase2 error:', e)
            try:
                trees = parser.parse(pat)
                for t in trees:
                    dump(t)
            except Exception as e:
                print('phase3 error:', e)
            try:
                from himark.engine import execute
                print('execute on [x]:', execute(parser.parse(pat), '[x]'))
            except Exception as e:
                print('execute error:', e)
    except Exception as e:
        print('phase3 error:', e)
