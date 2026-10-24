"""Source coverage and deterministic regeneration guard against dropped content."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT.parent / 'historical'
sys.path.insert(0, str(ROOT / 'tools'))

from zil import Atom, Form, Prefix, Reader, head, name, source_forms
from zork.generated import ROUTINES


class TranslationTests(unittest.TestCase):
    def test_reader_comments_prefixes_and_adjacent_tokens(self):
        value = Reader('<TELL ;"ignored" D,MAILBOX "hello|\nworld" CR>').read()
        self.assertEqual(value, Form((Atom('TELL'), Atom('D'), Prefix(',', Atom('MAILBOX')),
                                     'hello\nworld', Atom('CR'))))
        value = Reader('<TABLE 1 ;<TABLE 99> #BYTE 2>').read()
        self.assertEqual(value.items[1:], (1, Prefix('#BYTE', 2)))

    def test_generated_game_content_is_complete(self):
        manifest = json.loads((ROOT / 'zork/generated/manifest.json').read_text())
        world = json.loads((ROOT / 'zork/generated/world.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['routines']), 440)
        expected = {world['globals'][symbol]: routine['python']
                    for symbol, routine in manifest['routines'].items()}
        self.assertEqual({key: routine.__name__ for key, routine in ROUTINES.items()}, expected)
        self.assertEqual(len(world['objects']), 250)
        self.assertEqual(manifest['objects'], 250)
        self.assertEqual(manifest['rooms'], 110)
        self.assertEqual(manifest['syntax_rules'], 267)

    @unittest.skipUnless(SOURCE_ROOT.exists(), 'Optional ../historical archive is absent')
    def test_every_active_routine_and_world_object_is_present(self):
        forms = list(source_forms(SOURCE_ROOT))
        manifest = json.loads((ROOT / 'zork/generated/manifest.json').read_text())
        routines = {name(f.items[1]) for _, f in forms if head(f) == 'ROUTINE'}
        self.assertEqual(routines, set(manifest['routines']))
        self.assertEqual(len(routines), 440)

    @unittest.skipUnless(SOURCE_ROOT.exists(), 'Optional ../historical archive is absent')
    def test_original_sources_match_recorded_build_inputs(self):
        manifest = json.loads((ROOT / 'zork/generated/manifest.json').read_text())
        for filename, digest in manifest['source_hashes'].items():
            with self.subTest(source=filename):
                self.assertEqual(hashlib.sha256((SOURCE_ROOT / filename).read_text(encoding='utf-8').encode()).hexdigest(), digest)

    @unittest.skipUnless(SOURCE_ROOT.exists(), 'Optional ../historical archive is absent')
    def test_translation_is_reproducible(self):
        directory = ROOT / 'zork/generated'
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        subprocess.run([sys.executable, 'tools/translate.py'], cwd=ROOT, capture_output=True,
                       text=True, check=True, timeout=30)
        after = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
