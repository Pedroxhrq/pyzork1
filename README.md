# Zork I — Python 3.15

The complete archived Zork I game, translated from ZIL into Python: **440
routines, 110 rooms, 250 game objects, 267 grammar rules, and 684 vocabulary
entries**. The Python package runs with the standard library alone.

The game logic is in generated Python functions under `zork/generated/`.
`zork/runtime.py` implements the original table, object, arithmetic, and input
operations. Playing does not require ZIL, a Z-machine interpreter, or a `.z3`
story file. The original source and historical artifacts are in the sibling
[historical/](../historical/README.md) directory. This directory, `python/`,
contains the rewritten game and its development files.

## Play

Install [Python 3.15.0 or newer](https://www.python.org/downloads/release/python-3150/),
then run from this directory (`zork1/python/`):

```console
python -m zork
```

On Windows, select the installed version explicitly if necessary:

```powershell
python3.15 -m zork
```

Try `look`, `open mailbox`, `read leaflet`, `north`, and `inventory`. The original
parser supports pronouns, abbreviations, multiple objects, `again`, `oops`, and
commands joined with `then`. `quit` asks for confirmation. End of input or Ctrl+C
also ends the session.

To install the optional console command:

```console
python -m pip install .
zork1
```

## Saves and scripts

Use `save` and `restore` inside the game. The default file is `zork-save.json` in
the working directory. Saves include the world, inventory, score, parser tables,
timers, and random state. They use a versioned JSON format tied to this build;
they are **not compatible with Z-machine/Quetzal save files**.

```console
python -m zork --save-file my-game.json
python -m zork --seed 1 --script tests/fixtures/opening.txt
python -m zork --help
```

`--seed` makes random events reproducible. Script files contain one command per
line and finish at EOF. `script`/`unscript` write a transcript to
`zork-transcript.txt`. `#record`/`#unrecord` record input in `zork-commands.txt`;
`#command` replays that file. Override the paths with `--transcript` and
`--recording`. The display keeps the original release 119 / serial 880429 banner.

## Development and validation

Run these commands from `python/`. Source coverage tests, regeneration, and live
comparisons require the sibling `historical/` directory from the full repository.
The Python wheel and source distribution contain only the Python version.

```console
python -m unittest discover -v
python tools/translate.py
```

All 27 tests pass on Python 3.15.0. They cover parser behavior, combat, timers,
restart, isolated sessions, save/restore across processes, recording, integrity,
and reproducible generation. Four complete output transcripts are checked against
hashes captured from the original story using an independent interpreter. The
full walkthrough reaches **350 points and the final barrow ending** in 440 input
commands / 507 game moves with seed 25.

An optional live comparison can be run with a separate checkout of
[xyppy](https://github.com/theinternetftw/xyppy):

```console
python tools/compare_original.py --xyppy /path/to/xyppy --commands tests/fixtures/walkthrough.txt --seed 25
```

The fixture runner strips its comment lines. The game itself reads raw commands.
The interpreter is a development-only comparison tool and is not bundled with
the Python game.

The translator is specifically scoped to the sources in `../historical/`. Edit a
source routine or the translator, regenerate, and run the tests together. Macro semantics
and runtime operations are implemented explicitly in the translator/runtime;
changing a ZIL macro definition requires updating its Python implementation too.
`zork/generated/manifest.json` maps every routine back to its source file and
records normalized source hashes and generated artifact hashes. Its source
filenames are relative to `historical/`.

See [ANALYSIS.md](ANALYSIS.md) for the full project inventory, architecture,
translation choices, and verification limits. The game retains the [MIT
license](LICENSE); the external full-walkthrough test data has a separate
[GPL-3.0 license and attribution](tests/fixtures/README.md) and is excluded from
the game wheel.
