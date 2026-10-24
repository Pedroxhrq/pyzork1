"""Checks for the ZIL semantics on which the translated game depends."""

import io
import unittest

from zork import Runtime
from zork.vocabulary import dictionary_key


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.game = Runtime(input=io.StringIO(), output=io.StringIO(), seed=1)

    def test_signed_arithmetic(self):
        r = self.game
        self.assertEqual(r.signed(65535), -1)
        self.assertEqual(r.signed(32768), -32768)
        self.assertEqual(r.divide(-7, 3), -2)
        self.assertEqual(r.divide(7, -3), -2)
        self.assertEqual(r.modulo(-7, 3), -1)
        with self.assertRaises(ZeroDivisionError):
            r.divide(1, 0)

    def test_byte_and_word_aliasing_and_store_return_value(self):
        r = self.game
        table = r.globals['P-ITBL']
        self.assertEqual(r.put(table, 0, 0), 1)
        r.put(table, 1, -2)
        self.assertEqual(r.getb(table, 2), 255)
        self.assertEqual(r.getb(table, 3), 254)
        self.assertEqual(r.get(table, 1), -2)
        self.assertEqual(r.putb(table, 3, 0), 1)
        self.assertEqual(r.get(table, 1), -256)

    def test_object_tree_and_cycle_prevention(self):
        r = self.game
        g = r.globals
        r.move(g['LAMP'], g['MAILBOX'])
        r.move(g['SWORD'], g['MAILBOX'])
        self.assertEqual(r.first(g['MAILBOX']), g['SWORD'])
        self.assertEqual(r.sibling(g['SWORD']), g['LAMP'])
        with self.assertRaises(ValueError):
            r.move(g['MAILBOX'], g['LAMP'])
        r.remove(g['LAMP'])
        self.assertEqual(r.parent(g['LAMP']), 0)

    def test_properties_default_and_mutation(self):
        r = self.game
        g = r.globals
        self.assertEqual(r.get_prop(g['ADVERTISEMENT'], g['P?SIZE']), 2)
        self.assertEqual(r.get_prop(g['MAILBOX'], g['P?TVALUE']), 0)
        r.put_prop(g['TROLL'], g['P?STRENGTH'], -5)
        self.assertEqual(r.get_prop(g['TROLL'], g['P?STRENGTH']), -5)

    def test_clock_counts_down_once_and_disables_events(self):
        r = self.game
        g = r.globals
        events = []
        r.routines = dict(r.routines)
        r.routines[32000] = lambda runtime: events.append(runtime.globals['MOVES']) or 1
        timer = r.call(g['QUEUE'], 32000, 2)
        r.put(timer, g['C-ENABLED?'], 1)
        g['P-WON'] = 1
        self.assertEqual(r.call(g['CLOCKER']), 0)
        self.assertEqual(r.call(g['CLOCKER']), 1)
        self.assertEqual(r.call(g['CLOCKER']), 0)
        self.assertEqual(events, [1])
        r.call(g['QUEUE'], 32000, -1)
        r.call(g['CLOCKER'])
        r.call(g['CLOCKER'])
        r.put(timer, g['C-ENABLED?'], 0)
        r.call(g['CLOCKER'])
        self.assertEqual(events, [1, 3, 4])

    def test_game_artifact_integrity(self):
        self.assertEqual(self.game.verify(), 1)

    def test_dictionary_counts_encoded_characters(self):
        for word, expected in [('advertisement', 'advert'), ('#command', '#comm'),
                               ('$verify', '$ve'), ('air-pump', 'air-p'),
                               ('pdp10', 'pdp1'), ('trap-door', 'trap-')]:
            with self.subTest(word=word):
                self.assertEqual(dictionary_key(word), expected)


if __name__ == '__main__':
    unittest.main()
