# Regression command fixtures

`opening.txt`, `parser.txt`, and `combat.txt` exercise the house, noun inference,
OOPS, AGAIN, pronouns, compound commands, multiple objects, containers, combat,
and the dam. They are part of this project's MIT-licensed tests.

`walkthrough.txt` is external **GPL-3.0 test data**, adapted from
[avwohl/zwalker: zork1_verified_350.txt](https://github.com/avwohl/zwalker/blob/main/walkthroughs/zork1_verified_350.txt).
Its license is reproduced in `WALKTHROUGH-LICENSE.txt`. The modification adds the
map and final barrow ending. This fixture is not included in the game wheel.
The Python game and its original Zork source retain the MIT license included at
the repository root.

All four reference transcript hashes in `test_game.py` were captured from the
original archive's `COMPILED/zork1.z3` (release 119, serial 880429) using the independent
[xyppy interpreter](https://github.com/theinternetftw/xyppy). The reference run
uses Python's seeded random generator so both implementations receive the same
random sequence. Only whitespace is normalized before hashing. The full fixture
uses seed 25: 440 input commands, 350 points, 507 game moves, and the barrow ending.

Lines beginning with `# ` are fixture comments. The test runner removes them;
raw game scripts supplied to `--script` should contain commands only.
