"""Command-line entry point: python -m zork."""

import argparse
from contextlib import ExitStack
from pathlib import Path

from . import Runtime


def main():
    parser = argparse.ArgumentParser(description='Zork I: The Great Underground Empire (Python edition)')
    parser.add_argument('--seed', type=int, help='seed for reproducible random events')
    parser.add_argument('--save-file', type=Path, default=Path('zork-save.json'))
    parser.add_argument('--script', type=Path, help='read commands from a UTF-8 file; exit at its end')
    parser.add_argument('--transcript', type=Path, default=Path('zork-transcript.txt'))
    parser.add_argument('--recording', type=Path, default=Path('zork-commands.txt'))
    args = parser.parse_args()
    with ExitStack() as stack:
        try:
            source = stack.enter_context(args.script.open(encoding='utf-8')) if args.script else None
        except OSError as error:
            parser.error(str(error))
        Runtime(input=source, seed=args.seed, save_file=args.save_file,
                transcript=args.transcript, recording=args.recording).run()


if __name__ == '__main__':
    main()
