"""Python implementation of the small ZIL runtime used by Zork I.

The game logic lives in generated Python functions. This module supplies
16-bit arithmetic, mutable tables, the object tree, terminal I/O and saves.
It does not execute Z-machine instructions or require a story file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import random
import re
import sys
import tempfile
from typing import TextIO

from .vocabulary import dictionary_key


class RoutineReturn(Exception):
    def __init__(self, value: int):
        self.value = value


class BlockReturn(RoutineReturn):
    def __init__(self, target: str, value: int):
        super().__init__(value)
        self.target = target


class BlockAgain(Exception):
    def __init__(self, target: str):
        self.target = target


class Restart(Exception):
    """Unwind Python frames before restarting the game."""


class Restored(Exception):
    """Resume a saved game at its next command boundary."""


class EndOfGame(Exception):
    """Normal quit or end of input."""


@dataclass(slots=True)
class GameObject:
    name: str
    description: str
    parent: int = 0
    children: list[int] = field(default_factory=list)
    flags: set[int] = field(default_factory=set)
    properties: dict[int, int] = field(default_factory=dict)


class Runtime:
    """One isolated game, with injectable input, output and random seed."""

    def __init__(self, *, input: TextIO | None = None, output: TextIO | None = None,
                 seed: int | None = None, save_file: Path | str = 'zork-save.json',
                 transcript: Path | str = 'zork-transcript.txt',
                 recording: Path | str = 'zork-commands.txt',
                 command_file: Path | str | None = None):
        from .generated import ROUTINES

        self.input = input if input is not None else sys.stdin
        self.output = output if output is not None else sys.stdout
        self.seed = seed
        self.save_file = Path(save_file)
        self.transcript = Path(transcript)
        self.recording = Path(recording)
        self.command_file = Path(command_file) if command_file is not None else None
        self.routines = ROUTINES
        self.package = files('zork.generated')
        self.image_text = self.package.joinpath('world.json').read_text(encoding='utf-8')
        self.artifact_hashes = json.loads(self.package.joinpath('manifest.json').read_text(encoding='utf-8'))['artifact_hashes']
        self.image_id = hashlib.sha256(json.dumps(self.artifact_hashes, sort_keys=True).encode()).hexdigest()
        self.record_commands = False
        self.replay: TextIO | None = None
        self.reset()

    def reset(self):
        image = json.loads(self.image_text)
        self.globals = image['globals']
        self.memory = bytearray.fromhex(image['memory'])
        self.strings = {int(k): v for k, v in image['strings'].items()}
        self.sizes = {int(k): v for k, v in image['sizes'].items()}
        self.defaults = {int(k): v for k, v in image['defaults'].items()}
        self.dictionary = image['dictionary']
        self.words = {v: k for k, v in self.dictionary.items()}
        self.globals_by_number = {int(k): v for k, v in image['globals_by_number'].items()}
        self.mutable_globals = set(self.globals_by_number.values())
        self.objects = {
            int(k): GameObject(v['name'], v['description'], v['parent'],
                               v['children'], set(v['flags']),
                               {int(p): address for p, address in v['properties'].items()})
            for k, v in image['objects'].items()
        }
        self.rng = random.Random(self.seed)

    @staticmethod
    def signed(value: int) -> int:
        return ((value + 32768) & 65535) - 32768

    @classmethod
    def divide(cls, a: int, b: int) -> int:
        a, b = cls.signed(a), cls.signed(b)
        if not b:
            raise ZeroDivisionError('ZIL division by zero')
        return cls.signed((abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1))

    @classmethod
    def modulo(cls, a: int, b: int) -> int:
        return cls.signed(a) - cls.divide(a, b) * cls.signed(b)

    def call(self, routine: int, *args: int) -> int:
        if not routine:
            return 0
        try:
            return self.routines[routine](self, *args)
        except BlockReturn:
            raise
        except RoutineReturn as result:
            return result.value

    def get(self, table: int, index: int) -> int:
        offset = table + index * 2
        return self.signed((self.memory[offset] << 8) | self.memory[offset + 1])

    def getb(self, table: int, index: int) -> int:
        return self.memory[table + index]

    def put(self, table: int, index: int, value: int) -> int:
        offset = table + index * 2
        self.memory[offset:offset + 2] = (value & 65535).to_bytes(2, 'big')
        return 1

    def putb(self, table: int, index: int, value: int) -> int:
        self.memory[table + index] = value & 255
        return 1

    def prop_address(self, obj: int, prop: int) -> int:
        return self.objects[obj].properties.get(prop, 0) if obj else 0

    def prop_size(self, address: int) -> int:
        return self.sizes.get(address, 0)

    def get_prop(self, obj: int, prop: int) -> int:
        address = self.prop_address(obj, prop)
        if not address:
            return self.defaults.get(prop, 0)
        return self.getb(address, 0) if self.sizes[address] == 1 else self.get(address, 0)

    def put_prop(self, obj: int, prop: int, value: int) -> int:
        address = self.prop_address(obj, prop)
        if not address:
            raise ValueError(f'Object {obj} has no property {prop}')
        return self.putb(address, 0, value) if self.sizes[address] == 1 else self.put(address, 0, value)

    def next_prop(self, obj: int, prop: int) -> int:
        props = sorted(self.objects[obj].properties, reverse=True)
        return next((p for p in props if not prop or p < prop), 0)

    def flag(self, obj: int, flag: int) -> int:
        return int(bool(obj) and flag in self.objects[obj].flags)

    def set_flag(self, obj: int, flag: int) -> int:
        self.objects[obj].flags.add(flag)
        return 1

    def clear_flag(self, obj: int, flag: int) -> int:
        self.objects[obj].flags.discard(flag)
        return 1

    def parent(self, obj: int) -> int:
        return self.objects[obj].parent if obj else 0

    def inside(self, obj: int, parent: int) -> int:
        return int(self.parent(obj) == parent)

    def first(self, obj: int) -> int:
        children = self.objects[obj].children if obj else []
        return children[0] if children else 0

    def sibling(self, obj: int) -> int:
        parent = self.parent(obj)
        if not parent:
            return 0
        children = self.objects[parent].children
        i = children.index(obj) + 1
        return children[i] if i < len(children) else 0

    def remove(self, obj: int) -> int:
        parent = self.parent(obj)
        if parent:
            self.objects[parent].children.remove(obj)
        self.objects[obj].parent = 0
        return 1

    def move(self, obj: int, parent: int) -> int:
        ancestor = parent
        while ancestor:
            if ancestor == obj:
                raise ValueError('An object cannot contain itself')
            ancestor = self.parent(ancestor)
        self.remove(obj)
        self.objects[obj].parent = parent
        if parent:
            self.objects[parent].children.insert(0, obj)
        return 1

    def value(self, variable: int | str) -> int:
        return self.globals[variable if isinstance(variable, str) else self.globals_by_number[variable]]

    def random(self, maximum: int) -> int:
        maximum = self.signed(maximum)
        if maximum <= 0:
            self.rng.seed(-maximum if maximum else None)
            return 0
        return self.rng.randint(1, maximum)

    def write(self, text: str) -> int:
        self.output.write(text)
        self.output.flush()
        if self.get(0, 8) & 1:
            try:
                with self.transcript.open('a', encoding='utf-8') as stream:
                    stream.write(text)
            except OSError as error:
                self.put(0, 8, self.get(0, 8) & ~1)
                self.output.write(f'\nCannot write transcript: {error}\n')
        return 1

    def print_text(self, text: int | str) -> int:
        return self.write(text if isinstance(text, str) else self.strings[text & 65535])

    def print_object(self, obj: int) -> int:
        return self.write(self.objects[obj].description)

    def print_article(self, obj: int) -> int:
        description = self.objects[obj].description
        return self.write(('an ' if description[:1].lower() in 'aeiou' else 'a ') + description)

    def print_number(self, number: int) -> int:
        return self.write(str(self.signed(number)))

    def print_char(self, char: int) -> int:
        return self.write('\n' if char == 13 else chr(char))

    def print_word(self, word: int) -> int:
        return self.write(self.words[word])

    def read(self, text_buffer: int, parse_buffer: int) -> int:
        source = self.replay if self.replay is not None else self.input
        line = source.readline()
        if not line and self.replay is not None:
            self.replay.close()
            self.replay = None
            line = self.input.readline()
        if not line:
            raise EndOfGame
        if self.record_commands:
            try:
                with self.recording.open('a', encoding='utf-8') as stream:
                    stream.write(line.rstrip('\r\n') + '\n')
            except OSError as error:
                self.record_commands = False
                self.write(f'Cannot record commands: {error}\n')
        if self.get(0, 8) & 1:
            with self.transcript.open('a', encoding='utf-8') as stream:
                stream.write(line)
        # The original parser expects V3 byte offsets and six-character words.
        limit = self.getb(text_buffer, 0) - 1
        line = line.rstrip('\r\n').lower().encode('ascii', errors='replace')[:limit].decode('ascii')
        for i, char in enumerate(line, 1):
            self.putb(text_buffer, i, ord(char))
        self.putb(text_buffer, len(line) + 1, 0)
        tokens = list(re.finditer(r'[^\s.,"]+|[.,"]', line))[:self.getb(parse_buffer, 0)]
        self.putb(parse_buffer, 1, len(tokens))
        for i, token in enumerate(tokens):
            offset = 2 + 4 * i
            self.put(parse_buffer + offset, 0, self.dictionary.get(dictionary_key(token[0]), 0))
            self.putb(parse_buffer, offset + 2, len(token[0]))
            self.putb(parse_buffer, offset + 3, token.start() + 1)
        return 1

    def snapshot(self) -> dict:
        return {
            'format': 'zork-python-save', 'version': 1, 'image': self.image_id,
            'globals': {k: self.globals[k] for k in self.mutable_globals},
            'memory': self.memory.hex(), 'random': self.rng.getstate(),
            'objects': {str(k): {'parent': o.parent, 'children': o.children[:],
                                 'flags': sorted(o.flags)} for k, o in self.objects.items()},
        }

    def load_snapshot(self, state: dict):
        """Validate the entire candidate before replacing any live state."""
        if (state.get('format'), state.get('version'), state.get('image')) != ('zork-python-save', 1, self.image_id):
            raise ValueError('Save belongs to a different game build or format')
        memory = bytearray.fromhex(state['memory'])
        if len(memory) != len(self.memory):
            raise ValueError('Invalid saved memory size')
        variables = state['globals']
        if set(variables) != self.mutable_globals or any(type(v) is not int for v in variables.values()):
            raise ValueError('Invalid saved globals')
        objects = {int(k): v for k, v in state['objects'].items()}
        if set(objects) != set(self.objects):
            raise ValueError('Invalid saved object set')
        seen = set()
        for obj_id, obj in objects.items():
            if obj['parent'] not in (0, *objects):
                raise ValueError('Invalid parent')
            if not isinstance(obj['flags'], list) or any(type(f) is not int or not 0 <= f < 32 for f in obj['flags']):
                raise ValueError('Invalid flags')
            for child in obj['children']:
                if child not in objects or child in seen or objects[child]['parent'] != obj_id:
                    raise ValueError('Invalid object links')
                seen.add(child)
            ancestors = {obj_id}
            parent = obj['parent']
            while parent:
                if parent in ancestors:
                    raise ValueError('Cyclic object tree')
                ancestors.add(parent)
                parent = objects[parent]['parent']
        if seen != {k for k, v in objects.items() if v['parent']}:
            raise ValueError('Incomplete object links')
        rng = random.Random()
        rng.setstate((state['random'][0], tuple(state['random'][1]), state['random'][2]))
        self.memory = memory
        self.globals.update(variables)
        self.rng = rng
        for obj_id, state_object in objects.items():
            obj = self.objects[obj_id]
            obj.parent = state_object['parent']
            obj.children = state_object['children'][:]
            obj.flags = set(state_object['flags'])

    def save(self) -> int:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.save_file.resolve().parent,
                                             prefix='.zork-save-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.snapshot(), stream)
                stream.write('\n')
            temporary.replace(self.save_file)
            return 1
        except (OSError, ValueError) as error:
            self.write(f'Cannot save game: {error}\n')
            return 0
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def restore(self) -> int:
        try:
            if self.save_file.stat().st_size > 2_000_000:
                raise ValueError('Save file is too large')
            self.load_snapshot(json.loads(self.save_file.read_text(encoding='utf-8')))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            self.write(f'Cannot restore game: {error}\n')
            return 0
        for key in ('P-CONT', 'P-OFLAG', 'P-MERGED', 'RESERVE-PTR', 'QUOTE-FLAG'):
            self.globals[key] = 0
        raise Restored

    def verify(self) -> int:
        return int(all(hashlib.sha256(self.package.joinpath(name).read_bytes()).hexdigest() == digest
                       for name, digest in self.artifact_hashes.items()))

    def input_file(self, stream: int) -> int:
        if not stream:
            if self.replay is not None:
                self.replay.close()
                self.replay = None
            return 1
        path = self.command_file or self.recording
        try:
            candidate = path.open(encoding='utf-8')
        except OSError as error:
            self.write(f'Cannot read commands: {error}\n')
            return 0
        if self.replay is not None:
            self.replay.close()
        self.replay = candidate
        return 1

    def output_stream(self, stream: int) -> int:
        if abs(stream) != 4:
            raise ValueError(f'Unsupported output stream: {stream}')
        self.record_commands = stream > 0
        return 1

    def quit(self):
        raise EndOfGame

    def restart(self):
        raise Restart

    def run(self):
        """Play until QUIT, EOF, or a keyboard interrupt."""
        entry = 'GO'
        try:
            while True:
                try:
                    self.call(self.globals[entry])
                    return
                except Restart:
                    output_flags = self.get(0, 8) & 3
                    self.reset()
                    self.put(0, 8, output_flags)
                    entry = 'GO'
                except Restored:
                    self.write('Ok.\n')
                    self.call(self.globals['V-FIRST-LOOK'])
                    entry = 'MAIN-LOOP'
        except (EndOfGame, KeyboardInterrupt):
            self.write('\n')
        finally:
            if self.replay is not None:
                self.replay.close()
                self.replay = None
