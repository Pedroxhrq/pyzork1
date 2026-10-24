"""Optional independent differential check against the archived story file.

Download https://github.com/theinternetftw/xyppy separately, then run from python/:
python tools/compare_original.py --xyppy PATH --commands tests/fixtures/opening.txt
xyppy is a validation tool only; the Python game never imports it.
"""

import argparse
import difflib
import io
from pathlib import Path
import random
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT.parent / 'historical'
sys.path.insert(0, str(ROOT))

from zork import Runtime


def original_transcript(story, commands, seed, observe=None):
    from xyppy import ops, ops_impl, term, zenv
    from xyppy.zmath import to_signed_word

    transcript = io.StringIO()
    lines = iter(commands.splitlines())

    class Screen:
        def write(self, text):
            transcript.write(text)

        def get_line_of_input(self, **kwargs):
            if observe is not None:
                observe(env)
            return next(lines)

        def flush(self):
            pass

    term.get_size = lambda: (80, 25)
    env = zenv.Env(story, SimpleNamespace(no_slow_scroll=True))
    env.screen = Screen()
    env.output_buffer[1] = env.screen
    rng = random.Random(seed)

    def random_op(env, info):
        maximum = to_signed_word(info.operands[0])
        if maximum <= 0:
            rng.seed(-maximum if maximum else None)
            value = 0
        else:
            value = rng.randint(1, maximum)
        ops_impl.set_var(env, info.store_var, value)

    ops.random_ = random_op
    ops.setup_opcodes(env)
    try:
        for _ in range(10_000_000):
            zenv.step(env)
        raise RuntimeError('Reference instruction limit exceeded')
    except (StopIteration, SystemExit):
        return transcript.getvalue()


def normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xyppy', type=Path, required=True)
    parser.add_argument('--commands', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args()
    sys.path.insert(0, str(args.xyppy.resolve()))
    commands = '\n'.join(line for line in args.commands.read_text(encoding='utf-8').splitlines()
                         if line.strip() and not line.startswith('# ')) + '\n'
    expected = original_transcript((SOURCE_ROOT / 'COMPILED/zork1.z3').read_bytes(), commands, args.seed)
    output = io.StringIO()
    game = Runtime(input=io.StringIO(commands), output=output, seed=args.seed)
    game.run()
    actual = output.getvalue()
    if normalize(expected) != normalize(actual):
        for line in difflib.unified_diff(normalize(expected).split('>'), normalize(actual).split('>'), fromfile='original', tofile='python', lineterm=''):
            print(line)
        return 1
    print(f'MATCH: {len(commands.splitlines())} commands; score {game.globals["SCORE"]}; moves {game.globals["MOVES"]}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
