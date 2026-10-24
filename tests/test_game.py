"""Behavioral regression tests, including an independently verified full win."""

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from zork import Runtime

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'

# Captured independently from release 119 / serial 880429 using xyppy.
# Whitespace alone is normalized; every word and punctuation mark must match.
ORIGINAL_TRANSCRIPTS = {
    'opening': (1, '61348ab24a5f02b814cf60c1e480a78b856e69e20931134a9b246edca10c16e5'),
    'parser': (1, '747c1dbaba6337a09e0349709ade7efdf3194cd1dca740f2a712f7a1d17c1cc9'),
    'combat': (1, 'e4dc75ebd1ae52031290eb388f4f67af9e8ba8375f840502aa51f457de916f10'),
    'walkthrough': (25, 'cb6178cc0c36a3280ad23205592f99e136cb2058041cd888f1050b5efd1e4c9f'),
}


def fixture(name):
    return '\n'.join(line for line in (FIXTURES / f'{name}.txt').read_text(encoding='utf-8').splitlines()
                     if line.strip() and not line.startswith('# ')) + '\n'


def play(commands='', **kwargs):
    output = io.StringIO()
    game = Runtime(input=io.StringIO(commands), output=output, **kwargs)
    game.run()
    return game, output.getvalue()


class GameTests(unittest.TestCase):
    def test_transcripts_match_original_story(self):
        for name, (seed, expected) in ORIGINAL_TRANSCRIPTS.items():
            with self.subTest(scenario=name):
                game, output = play(fixture(name), seed=seed)
                normalized = re.sub(r'\s+', ' ', output).strip()
                self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), expected)
                if name == 'walkthrough':
                    self.assertEqual(game.globals['SCORE'], 350)
                    self.assertEqual(game.globals['MOVES'], 507)
                    self.assertEqual(game.globals['WON-FLAG'], 1)
                    self.assertIn('Inside the Barrow', output)
                    self.assertIn('Master Adventurer', output)

    def test_opening_world_state(self):
        game, _ = play(fixture('opening'), seed=1)
        g = game.globals
        self.assertEqual(g['HERE'], g['CELLAR'])
        self.assertEqual(g['SCORE'], 35)
        self.assertEqual(g['MOVES'], 14)
        self.assertEqual(game.parent(g['LAMP']), g['ADVENTURER'])
        self.assertEqual(game.flag(g['LAMP'], g['ONBIT']), 1)
        self.assertEqual(game.flag(g['TRAP-DOOR'], g['OPENBIT']), 0)

    def test_empty_and_unknown_input_do_not_advance_time(self):
        game, output = play('\nnotaword\n', seed=1)
        self.assertEqual(game.globals['MOVES'], 0)
        self.assertIn('I beg your pardon?', output)
        self.assertIn('I don\'t know the word "notaword"', output)

    def test_restart_resets_world_and_score(self):
        game, output = play('open mailbox\nnorth\nrestart\ny\nlook\n', seed=1)
        g = game.globals
        self.assertEqual(g['HERE'], g['WEST-OF-HOUSE'])
        self.assertEqual(g['SCORE'], 0)
        self.assertEqual(g['MOVES'], 1)
        self.assertFalse(game.flag(g['MAILBOX'], g['OPENBIT']))
        self.assertIn('Restarting.', output)

    def test_quit_confirmation_can_be_declined(self):
        game, output = play('quit\nn\nnorth\nquit\ny\neast\n')
        self.assertEqual(game.globals['HERE'], game.globals['NORTH-OF-HOUSE'])
        self.assertEqual(game.globals['MOVES'], 1)

    def test_games_have_independent_mutable_state(self):
        first, _ = play('open mailbox\ntake leaflet\n', seed=1)
        second, _ = play('', seed=1)
        g = second.globals
        self.assertFalse(second.flag(g['MAILBOX'], g['OPENBIT']))
        self.assertEqual(second.parent(g['ADVERTISEMENT']), g['MAILBOX'])
        self.assertNotEqual(first.parent(g['ADVERTISEMENT']), second.parent(g['ADVERTISEMENT']))

    def test_long_unicode_input_is_bounded(self):
        game, output = play(('é' * 500) + '\nlook\n')
        self.assertIn('West of House', output)
        self.assertEqual(game.globals['MOVES'], 1)

    def test_script_transcript_and_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / 'transcript.txt'
            recording = Path(directory) / 'commands.txt'
            game, output = play('script\n#record\nlook\n#unrecord\nunscript\n',
                                transcript=transcript, recording=recording)
            self.assertIn('West of House', transcript.read_text())
            self.assertEqual(recording.read_text(), 'look\n#unrecord\n')
            self.assertFalse(game.get(0, 8) & 1)
            self.assertFalse(game.record_commands)

    def test_recorded_commands_can_be_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = Path(directory) / 'commands.txt'
            commands.write_text('north\neast\n', encoding='utf-8')
            game, _ = play('#command\n', command_file=commands)
            self.assertEqual(game.globals['HERE'], game.globals['EAST-OF-HOUSE'])

    def test_installed_command_line_shape(self):
        result = subprocess.run([sys.executable, '-m', 'zork', '--seed', '1'],
                                input='open mailbox\n', text=True, capture_output=True,
                                cwd=ROOT, timeout=10, check=True)
        self.assertIn('reveals a leaflet', result.stdout)
        self.assertFalse(result.stderr)


class SaveTests(unittest.TestCase):
    def test_save_restore_preserves_inventory_score_and_room(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game.json'
            game, output = play(fixture('opening') + 'save\ndrop lamp\ndrop sword\nrestore\ninventory\n',
                                save_file=path, seed=1)
            g = game.globals
            self.assertEqual(g['HERE'], g['CELLAR'])
            self.assertEqual(g['SCORE'], 35)
            self.assertEqual(game.parent(g['SWORD']), g['ADVENTURER'])
            self.assertEqual(game.parent(g['LAMP']), g['ADVENTURER'])
            self.assertIn('providing light', output.split('>Ok.')[-1])
            self.assertEqual(json.loads(path.read_text())['format'], 'zork-python-save')
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_save_can_be_restored_in_a_new_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game.json'
            play('open mailbox\ntake leaflet\nnorth\nsave\n', save_file=path, seed=4)
            result = subprocess.run([sys.executable, '-m', 'zork', '--save-file', str(path)],
                                    input='restore\ninventory\nlook\n', text=True,
                                    capture_output=True, cwd=ROOT, timeout=10, check=True)
            self.assertIn('A leaflet', result.stdout)
            self.assertIn('North of House', result.stdout)

    def test_random_state_round_trip(self):
        game, _ = play(seed=3)
        snapshot = json.loads(json.dumps(game.snapshot()))
        expected = [game.random(100) for _ in range(20)]
        game.load_snapshot(snapshot)
        self.assertEqual([game.random(100) for _ in range(20)], expected)

    def test_rejected_snapshot_is_atomic(self):
        game, _ = play('north\n', seed=3)
        before = game.snapshot()
        for damage in ('version', 'image', 'memory', 'cycle'):
            with self.subTest(damage=damage):
                broken = json.loads(json.dumps(before))
                if damage == 'version':
                    broken['version'] = 999
                elif damage == 'image':
                    broken['image'] = 'different-game'
                elif damage == 'memory':
                    broken['memory'] = '00'
                else:
                    key = str(game.globals['ROOMS'])
                    broken['objects'][key]['parent'] = int(key)
                with self.assertRaises(ValueError):
                    game.load_snapshot(broken)
                self.assertEqual(game.snapshot(), before)

    def test_missing_and_corrupt_save_fail_without_ending_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game.json'
            for content in (None, '{bad json', '{}'):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content)
                    game, output = play('restore\nnorth\n', save_file=path)
                    self.assertIn('Cannot restore game', output)
                    self.assertEqual(game.globals['HERE'], game.globals['NORTH-OF-HOUSE'])

    def test_unwritable_save_path_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            game, output = play('save\nnorth\n', save_file=Path(directory) / 'missing' / 'game.json')
            self.assertIn('Cannot save game', output)
            self.assertEqual(game.globals['HERE'], game.globals['NORTH-OF-HOUSE'])


if __name__ == '__main__':
    unittest.main()
