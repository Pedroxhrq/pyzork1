# Project analysis and Python migration

## Scope of the archive

This standalone repository contains the Python implementation at its root.
The original historical archive is optional and is not included. In the inventory
below, original paths describe that archive; Python destinations are relative to
the repository root (or `zork/` for generated modules and data). Development
tools can read a separately restored archive at `../historical/`.

The original repository contains 11,953 lines across ten ZIL files, with no
Python application, modern build configuration, or automated tests. `zork1.zil`
selects the version-3 ZIP target and Zork number 1, then includes nine files in a
specific order. Generic files also contain conditional Zork II/III code; those
branches are inactive in this game. The Python translation selects the same
Zork I branch and compiled `PREDGEN` implementation of `PERFORM`.

| Original file | Responsibility | Python destination |
| --- | --- | --- |
| `zork1.zil` | Include graph, version selection, property defaults | Build validation, `world.json`, CLI |
| `gmacros.zil` | Output/predicate macros, random selection; 3 runtime routines | `tools/translate.py`, `generated/gmacros.py` |
| `gsyntax.zil` | 267 grammar rules, verb/preposition synonyms, ignored words | Generated vocabulary, syntax/action tables |
| `1dungeon.zil` | 110 rooms, local objects, exits, startup; 4 routines | `world.json`, `generated/z1dungeon.py` |
| `gglobals.zil` | Shared scenery, player/global objects; 10 routines | `world.json`, `generated/gglobals.py` |
| `gclock.zil` | Event queue and turn processing; 3 routines | `generated/gclock.py` |
| `gmain.zil` | Command loop and action dispatch; 3 routines | `generated/gmain.py` |
| `gparser.zil` | Token interpretation, object resolution, disambiguation; 42 routines | `generated/gparser.py` |
| `gverbs.zil` | General actions, containment, movement, descriptions; 189 routines | `generated/gverbs.py` |
| `1actions.zil` | Puzzles, combat, thief, lighting, death, scoring; 186 routines | `generated/z1actions.py` |
| `parser.cmp` | Historical comparison against another parser revision | Preserved as historical documentation; not an active include |
| `zork1.record` | Compiler log and symbol inventory | Used to cross-check counts; preserved |
| `zork1.errors` | Successful assembler report, layout, unused symbols | Preserved |
| `zork1.chart` | Release/size/object/global/vocabulary summary | Preserved |
| `zork1.serial` | Historical build bookkeeping value | Preserved; not the story header serial |
| `zork1freq.xzap` | Generated frequent-string compression records | Preserved; Python strings do not need this compression |
| `zork1.zip`, `COMPILED/zork1.z3` | Identical 86,838-byte version-3 story images | Independent validation reference only |
| `README.md`, `LICENSE` | Provenance and MIT license | Original README in `historical/`; unchanged license also included with Python |

The `.zip` file is a Z-machine story image, not a ZIP archive. Both story copies
have SHA-256 `37084966477dff679282de42974b2077156b1bd68fad92a65d4ea94d8eb64d79`
and identify themselves as release 119, serial 880429. The historical report
lists 250 objects and 684 vocabulary entries; the regenerated world matches both.
The 250 objects include the 110 rooms, plus 140 other objects. There are 32 flags
and 30 properties, including directions.

## Implementation

The target is Python 3.15, whose stable 3.15.0 release is documented by
[Python.org](https://www.python.org/downloads/release/python-3150/). The application
has no runtime dependencies. Setuptools is needed only for packaging.

`tools/zil.py` reads forms, lists, strings, comments, reference prefixes, typed
table entries, and compile-time conditionals. `tools/translate.py` lowers all
440 active routines into Python functions containing ordinary control flow and
runtime calls. This is a source translation, not a bytecode interpreter. Each
generated function is named after its ZIL routine; the manifest records the
mapping. `world.json` contains data only: objects, strings, property records,
grammar, dictionaries, initial globals, and tables.

Both development tools read originals from the optional sibling `historical/`
directory. Run development commands from the repository root; GitHub Actions
uses that working directory too. Three archive-dependent tests skip when the
archive directory is absent. All gameplay, artifact integrity, and generated
content checks still run. An archive that exists but is incomplete fails the
source checks.

The implementation deliberately preserves low-level semantics that affect play:

- Signed 16-bit arithmetic, division toward zero, byte/word table aliasing, and
  the true result of store operations. A zero-valued store still returns true;
  this matters when healing interrupts a `wait` command.
- Ordered object children and siblings, property defaults, mutable flags,
  conditional/function/door exits, and shared local/global scenery.
- Six **encoded** dictionary characters. Alphabet shifts consume space, so
  `trap-door` and `#command` have different effective lengths from plain words.
- Local block returns versus routine returns, loop restarts, short-circuiting,
  left-to-right evaluation, and the original timer queue.
- Original messages, parser, puzzle logic, combat tables, random selection,
  inventory limits, scoring, deaths, and the final ending.

Each `Runtime` owns its globals, byte tables, object tree, and random generator.
Input/output streams and filenames are injectable, allowing deterministic tests
without a terminal. The CLI supports interactive play, command files, seeds,
transcripts, and command recording. Save files use JSON with build identity and
structural validation; writes replace the target atomically. Restore unwinds
Python execution to the next command boundary.

Generated output uses LF line endings on every platform. Source fingerprints
normalize line endings, while generated artifact fingerprints cover exact bytes.
The translator rejects unknown runtime operations and unresolved global
references. Regeneration tests verify byte-for-byte reproducibility.

## Verification and limits

Twenty-eight standard-library `unittest` tests cover semantic operations, generated
content, source translation, and real command sessions; three require the optional
archive. The optional comparison harness runs the original story through
[xyppy](https://github.com/theinternetftw/xyppy), using the same seeded random
generator, and compares complete transcripts after normalizing whitespace.

| Reference scenario | Input commands | Result |
| --- | ---: | --- |
| House, mailbox, lantern, trapdoor | 15 | Exact normalized transcript; score 35 |
| Parser corrections, pronouns, multiple objects, containers | 29 | Exact normalized transcript |
| Troll combat and travel toward the dam | 31 | Exact normalized transcript; score 40 |
| All treasures and the final barrow | 440 | Exact normalized transcript; 350 points, 507 moves, seed 25 |

The full run exercises the maze, thief and egg, reservoir, exorcism, rainbow,
coffin, coal mine machine, basket transport, river/boat, buried scarab, and
treasure deposits. This is substantial behavioral evidence, not exhaustive
coverage of every possible input, random seed, or puzzle failure path.

Intentional platform differences are the JSON save format, command-line file
selection, terminal-dependent wrapping, and Python's random generator. The same
numeric seed in an unrelated Z-machine interpreter need not produce the same
random sequence. The historical banner remains unchanged. The original source
archive's own bugs and quirks are preserved unless a Python runtime requirement
necessitates different I/O behavior.

The standalone wheel contains only the Python package, generated world, metadata,
and MIT license. The archived sources, reference interpreter, original story,
and separately licensed walkthrough test fixture are unnecessary for playing.
