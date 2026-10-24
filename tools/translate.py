"""Translate every active Zork I routine to ordinary Python functions.

Run from the python/ directory: python tools/translate.py
The original ZIL sources live in the sibling historical/ directory.
The game imports the generated modules; it does not read ZIL or story bytecode.
"""

from collections import defaultdict
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

from zil import Atom, Form, Prefix, SOURCES, head, name, read_file, source_forms

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT.parent / 'historical'
DEST = ROOT / 'zork' / 'generated'
sys.path.insert(0, str(ROOT))
from zork.vocabulary import dictionary_key


def identifier(symbol):
    return 'fn_' + re.sub(r'[^a-z0-9_]', lambda m: {'-': '_', '?': '_q', '!': '_bang'}.get(m[0], '_'), symbol.lower())


class Compiler:
    def __init__(self, builder):
        self.builder = builder
        self.lines = []
        self.indent = 1
        self.serial = 0
        self.blocks = []

    def emit(self, line):
        self.lines.append('    ' * self.indent + line)

    def temp(self):
        self.serial += 1
        return f't{self.serial}'

    def expr(self, x):
        if isinstance(x, Prefix):
            if x.kind == '.':
                return f'l[{name(x.value)!r}]'
            if x.kind == ',':
                return f'g[{name(x.value)!r}]'
            if x.kind == '#DECL':
                return '0'
            if x.kind == "'":
                return self.expr(x.value)
            raise ValueError(x)
        if isinstance(x, Atom):
            if x.name in ('T', 'ELSE'):
                return '1'
            if re.fullmatch(r'\*[0-7]+\*', x.name):
                return str(int(x.name[1:-1], 8))
            if x.name in self.builder.global_names:
                return repr(x.name)  # VALUE takes a variable designator.
            return f'g[{x.name!r}]'
        if not isinstance(x, Form):
            if isinstance(x, str):
                return str(self.builder.string(x))
            if isinstance(x, int):
                return repr(x)
            raise ValueError(x)
        if not x.items:
            return '0'
        op, *args = x.items
        op = name(op)
        if op in ('SET', 'SETG'):
            value = self.expr(args[1])
            target = 'l' if op == 'SET' else 'g'
            self.emit(f'{target}[{name(args[0])!r}] = {value}')
            return f'{target}[{name(args[0])!r}]'
        if op in ('IGRTR?', 'DLESS?'):
            var = name(args[0])
            self.emit(f'l[{var!r}] = r.signed(l[{var!r}] {"+" if op == "IGRTR?" else "-"} 1)')
            rhs = self.expr(args[1])
            return f'int(r.signed(l[{var!r}]) {">" if op == "IGRTR?" else "<"} r.signed({rhs}))'
        if op == 'COND':
            result = self.temp()
            self.emit(f'{result} = 0')
            base = self.indent
            for clause in args:
                condition = self.expr(clause[0])
                test = self.temp()
                self.emit(f'{test} = {condition}')
                self.emit(f'if {test}:')
                self.indent += 1
                value = self.sequence(clause[1:]) if len(clause) > 1 else test
                self.emit(f'{result} = {value}')
                self.indent -= 1
                self.emit('else:')
                self.indent += 1
            self.emit('pass')
            self.indent = base
            return result
        if op in ('AND', 'OR'):
            result = self.temp()
            self.emit(f'{result} = {1 if op == "AND" else 0}')
            for arg in args:
                self.emit(f'if {"" if op == "AND" else "not "}{result}:')
                self.indent += 1
                value = self.expr(arg)
                self.emit(f'{result} = {value}')
                self.indent -= 1
            return result
        if op in ('RTRUE', 'RFALSE', 'RFATAL'):
            result = {'RTRUE': 1, 'RFALSE': 0, 'RFATAL': 2}[op]
            self.emit(f'raise RoutineReturn({result})')
            return '0'
        if op == 'RETURN':
            value = self.expr(args[0]) if args else '1'
            if self.blocks:
                self.emit(f'raise BlockReturn({self.blocks[-1]!r}, {value})')
            else:
                self.emit(f'raise RoutineReturn({value})')
            return '0'
        if op == 'AGAIN':
            if self.blocks:
                self.emit(f'raise BlockAgain({self.blocks[-1]!r})')
            else:
                self.emit('raise Restart()')
            return '0'
        if op in ('REPEAT', 'PROG'):
            block = self.temp()
            self.emit(f'{block} = 0')
            self.init_locals(args[0])
            self.emit('while True:')
            self.indent += 1
            self.emit('try:')
            self.indent += 1
            self.blocks.append(block)
            value = self.sequence(args[1:])
            self.blocks.pop()
            self.emit(f'{block} = {value}')
            if op == 'PROG':
                self.emit('break')
            self.indent -= 1
            self.emit('except BlockReturn as jump:')
            self.indent += 1
            self.emit(f'if jump.target != {block!r}:')
            self.emit('    raise')
            self.emit(f'{block} = jump.value')
            self.emit('break')
            self.indent -= 1
            self.emit('except BlockAgain as jump:')
            self.indent += 1
            self.emit(f'if jump.target != {block!r}:')
            self.emit('    raise')
            self.indent -= 2
            return block
        if op == 'TELL':
            i = 0
            while i < len(args):
                arg = args[i]
                if isinstance(arg, str):
                    self.emit(f'r.write({arg!r})')
                elif name(arg) in ('CR', 'CRLF'):
                    self.emit("r.write('\\n')")
                elif isinstance(arg, Atom):
                    i += 1
                    value = self.expr(args[i])
                    code = name(arg)
                    method = {'D': 'print_object', 'DESC': 'print_object', 'O': 'print_object',
                              'OBJ': 'print_object', 'A': 'print_article', 'AN': 'print_article',
                              'N': 'print_number', 'NUM': 'print_number', 'C': 'print_char',
                              'CHAR': 'print_char', 'CHR': 'print_char'}.get(code)
                    if method:
                        self.emit(f'r.{method}({value})')
                    else:
                        self.emit(f'r.print_text(r.get_prop({value}, g[{code!r}]))')
                else:
                    self.emit(f'r.print_text({self.expr(arg)})')
                i += 1
            return '1'
        if op in ('VERB?', 'PRSO?', 'PRSI?', 'ROOM?'):
            symbol = {'VERB?': 'PRSA', 'PRSO?': 'PRSO', 'PRSI?': 'PRSI', 'ROOM?': 'HERE'}[op]
            values = [f'g[{("V?" if op == "VERB?" else "") + a.name!r}]' if isinstance(a, Atom) else self.expr(a) for a in args]
            return f'int(g[{symbol!r}] in ({", ".join(values)},))'
        if op in ('ENABLE', 'DISABLE'):
            return f'r.put({self.expr(args[0])}, 0, {int(op == "ENABLE")})'
        if op == 'PROB':
            base = self.expr(args[0])
            return f'r.call(g["ZPROB"], {base})' if len(args) > 1 else f'int({base} > r.random(100))'
        if op == 'FLAMING?':
            a = self.expr(args[0])
            return f'int(r.flag({a}, g["FLAMEBIT"]) and r.flag({a}, g["ONBIT"]))'
        if op == 'OPENABLE?':
            a = self.expr(args[0])
            return f'int(r.flag({a}, g["DOORBIT"]) or r.flag({a}, g["CONTBIT"]))'
        # Evaluate arguments left-to-right before an expression can mutate locals.
        values = []
        for arg in args:
            value = self.expr(arg)
            t = self.temp()
            self.emit(f'{t} = {value}')
            values.append(t)
        v = ', '.join(values)
        if op in self.builder.routines:
            return f'r.call(g[{op!r}]{", " if v else ""}{v})'
        methods = {'GET': 'get', 'GETB': 'getb', 'PUT': 'put', 'PUTB': 'putb',
                   'GETP': 'get_prop', 'PUTP': 'put_prop', 'GETPT': 'prop_address',
                   'PTSIZE': 'prop_size', 'NEXTP': 'next_prop', 'FSET?': 'flag',
                   'FSET': 'set_flag', 'FCLEAR': 'clear_flag', 'LOC': 'parent',
                   'FIRST?': 'first', 'NEXT?': 'sibling', 'IN?': 'inside',
                   'MOVE': 'move', 'REMOVE': 'remove', 'RANDOM': 'random',
                   'APPLY': 'call', 'PRINT': 'print_text', 'PRINTI': 'print_text',
                   'PRINTD': 'print_object', 'PRINTB': 'print_word',
                   'PRINTN': 'print_number', 'PRINTC': 'print_char', 'VALUE': 'value',
                   'READ': 'read', 'SAVE': 'save', 'RESTORE': 'restore',
                   'QUIT': 'quit', 'RESTART': 'restart', 'VERIFY': 'verify',
                   'DIRIN': 'input_file', 'DIROUT': 'output_stream'}
        if op in methods:
            return f'r.{methods[op]}({v})'
        if op in ('EQUAL?', '==?', 'N==?'):
            return f'int({values[0]} {"not in" if op == "N==?" else "in"} ({", ".join(values[1:])},))'
        if op in ('0?', 'ZERO?', 'NOT', '1?'):
            return f'int({values[0]} == {int(op == "1?")})'
        if op in ('L?', 'G?'):
            return f'int(r.signed({values[0]}) {"<" if op == "L?" else ">"} r.signed({values[1]}))'
        if op in ('+', '-', '*', 'BAND', 'BOR'):
            operator = {'BAND': '&', 'BOR': '|'}.get(op, op)
            if op == '-' and len(values) == 1:
                return f'r.signed(-{values[0]})'
            return f'r.signed({f" {operator} ".join(values)})'
        if op in ('/', 'MOD'):
            return f'r.{"divide" if op == "/" else "modulo"}({v})'
        if op in ('REST', 'BACK'):
            return f'({values[0]} {"+" if op == "REST" else "-"} {values[1] if len(values) > 1 else 1})'
        if op == 'BTST':
            return f'int(({values[0]} & {values[1]}) == {values[1]})'
        if op == 'ABS':
            return f'abs(r.signed({v}))'
        if op == 'NTH':
            return f'r.get({values[0]}, {values[1]})'
        if op == 'CRLF':
            return "r.write('\\n')"
        raise ValueError(f'Unsupported operation: {op}')

    def sequence(self, expressions):
        result = '0'
        for x in expressions:
            if isinstance(x, Prefix) and x.kind == '#DECL':
                continue
            result = self.expr(x)
            t = self.temp()
            self.emit(f'{t} = {result}')
            result = t
        return result

    def init_locals(self, variables):
        for var in variables:
            key = name(var[0]) if isinstance(var, tuple) else name(var)
            value = self.expr(var[1]) if isinstance(var, tuple) else '0'
            self.emit(f'l[{key!r}] = {value}')

    def routine(self, form):
        _, symbol, params, *body = form.items
        self.lines = [f'def {identifier(symbol.name)}(r, *args):', f'    """{symbol.name}: translated from the archived ZIL routine."""']
        self.emit('g = r.globals')
        self.emit('l = {}')
        mode, index = 'required', 0
        for param in params:
            if isinstance(param, str):
                mode = param.lower()
                continue
            key = name(param[0]) if isinstance(param, tuple) else name(param)
            if mode == 'aux':
                self.init_locals([param])
            elif mode == 'required':
                self.emit(f'l[{key!r}] = args[{index}]')
                index += 1
            else:
                self.emit(f'if len(args) > {index}:')
                self.emit(f'    l[{key!r}] = args[{index}]')
                self.emit('else:')
                self.indent += 1
                self.init_locals([param])
                self.indent -= 1
                index += 1
        result = self.sequence(body)
        self.emit(f'return {result}')
        return '\n'.join(self.lines) + '\n'


class Builder:
    def __init__(self, forms):
        self.forms = forms
        self.g = {'T': 1, 'ZORK-NUMBER': 1}
        self.memory = bytearray(1024)
        self.strings = {}
        self.string_ids = {}
        self.objects = {}
        self.sizes = {}
        self.dictionary = {}
        self.word_parts = defaultdict(dict)
        self.routines = {name(f.items[1]): (s, f) for s, f in forms if head(f) == 'ROUTINE'}
        self.global_names = [name(f.items[1]) for _, f in forms if head(f) == 'GLOBAL']
        self.globals_by_number = {i + 16: n for i, n in enumerate(self.global_names)}
        self.defaults = {}
        self.global_defs = {name(f.items[1]): f.items[2] for _, f in forms if head(f) in ('GLOBAL', 'CONSTANT')}
        self.flags = []
        self.props = []
        self.directions = next(f.items[1:] for _, f in forms if head(f) == 'DIRECTIONS')

    def alloc(self, data):
        ptr = len(self.memory)
        self.memory.extend(data)
        if len(self.memory) >= 30000:
            raise ValueError('Data address space exhausted')
        return ptr

    def word(self, x):
        return (int(x) & 65535).to_bytes(2, 'big')

    def string(self, text):
        if text not in self.string_ids:
            ptr = 40000 + len(self.strings)
            self.strings[ptr] = text
            self.string_ids[text] = ptr
        return self.string_ids[text]

    def resolve(self, symbol):
        if symbol in self.g:
            return self.g[symbol]
        if symbol in self.global_defs:
            self.g[symbol] = self.evaluate(self.global_defs[symbol])
            return self.g[symbol]
        if re.fullmatch(r'\*[0-7]+\*', symbol):
            return int(symbol[1:-1], 8)
        raise ValueError(f'Unresolved symbol: {symbol}')

    def evaluate(self, x):
        if isinstance(x, Prefix):
            return self.evaluate(x.value)
        if isinstance(x, Atom):
            return self.resolve(x.name)
        if isinstance(x, int):
            return x
        if isinstance(x, str):
            return self.string(x)
        if isinstance(x, Form):
            if not x.items:
                return 0
            op = head(x)
            args = list(x.items[1:])
            if op in ('TABLE', 'LTABLE', 'PTABLE', 'ITABLE'):
                flags = []
                repeat = 1
                if op == 'ITABLE':
                    if isinstance(args[0], Atom):
                        flags.append(name(args.pop(0)))
                    repeat = args.pop(0)
                if args and isinstance(args[0], tuple):
                    flags += [name(a) for a in args.pop(0)]
                if op == 'ITABLE' and not args:
                    args = [0]
                data = bytearray()
                for a in args:
                    is_byte = 'BYTE' in flags or isinstance(a, Prefix) and a.kind == '#BYTE'
                    value = self.evaluate(a)
                    data.extend(bytes([value & 255]) if is_byte else self.word(value))
                data *= repeat
                if 'LEXV' in flags:
                    data = bytearray([repeat, 0]) + data
                elif op in ('LTABLE', 'PTABLE') or 'LENGTH' in flags:
                    count = len(args) * repeat
                    data = bytearray([count]) + data if 'BYTE' in flags else bytearray(self.word(count)) + data
                return self.alloc(data)
            raise ValueError(f'Unsupported initializer: {x}')
        raise ValueError(x)

    def add_word(self, word, part=None, value=0):
        key = dictionary_key(word)
        if key not in self.dictionary:
            self.dictionary[key] = self.alloc(bytes(7))
        if part:
            self.word_parts[key][part] = value
        self.g['W?' + word] = self.dictionary[key]
        return self.dictionary[key]

    def build(self):
        objects = [f for _, f in self.forms if head(f) in ('OBJECT', 'ROOM')]
        for i, f in enumerate(objects, 1):
            self.g[name(f.items[1])] = i
            self.objects[i] = {'name': name(f.items[1]), 'parent': 0, 'children': [], 'flags': [], 'properties': {}, 'description': ''}
        for i, symbol in enumerate(self.routines, 30000):
            self.g[symbol] = i
        for f in objects:
            for prop in f.items[2:]:
                key = name(prop[0])
                if key == 'FLAGS':
                    for flag in prop[1:]:
                        if name(flag) not in self.flags:
                            self.flags.append(name(flag))
                elif key not in ('IN', 'DESC') and key not in self.props and key not in [name(d) for d in self.directions]:
                    self.props.append(key)
        self.g.update({f: i for i, f in enumerate(self.flags)})
        self.g.update({'P?' + p: i + 1 for i, p in enumerate(self.props)})
        self.g.update({'P?' + name(d): 63 - i for i, d in enumerate(self.directions)})
        self.g['LOW-DIRECTION'] = 64 - len(self.directions)
        # Assign vocabulary roles and action numbers before evaluating tables.
        syntax = [f.items[1:] for _, f in self.forms if head(f) == 'SYNTAX']
        verbs = list(dict.fromkeys(name(s[0]) for s in syntax))
        actions = list(dict.fromkeys(name(s[s.index(Atom('=')) + 1]) for s in syntax))
        for i, action in enumerate(actions):
            self.g['V?' + action.removeprefix('V-')] = i
        for i, verb in enumerate(verbs):
            self.g['ACT?' + verb] = 255 - i
            self.add_word(verb, 'verb', 255 - i)
        for direction in self.directions:
            self.add_word(name(direction), 'direction', self.g['P?' + name(direction)])
        adjectives = list(dict.fromkeys(name(a) for f in objects for p in f.items[2:] if name(p[0]) == 'ADJECTIVE' for a in p[1:]))
        for i, adjective in enumerate(adjectives, 1):
            self.g['A?' + adjective] = i
            self.add_word(adjective, 'adjective', i)
        for f in objects:
            for p in f.items[2:]:
                if name(p[0]) == 'SYNONYM':
                    for a in p[1:]:
                        self.add_word(name(a), 'object')
        for _, f in self.forms:
            if head(f) == 'BUZZ':
                for a in f.items[1:]:
                    self.add_word(name(a), 'buzz')
        preps = []
        for s in syntax:
            for a in s[1:s.index(Atom('='))]:
                if isinstance(a, Atom) and a.name != 'OBJECT' and a.name not in preps:
                    preps.append(a.name)
        for i, prep in enumerate(preps, 1):
            self.g['PR?' + prep] = i
            self.add_word(prep, 'preposition', i)
        # Synonyms share each role, but retain their own dictionary address.
        for _, f in self.forms:
            if head(f) == 'SYNONYM':
                base = dictionary_key(name(f.items[1]))
                for a in f.items[2:]:
                    self.add_word(name(a))
                    self.word_parts[dictionary_key(name(a))].update(self.word_parts[base])
        for word, alias in (('.', 'PERIOD'), (',', 'COMMA'), ('"', 'QUOTE')):
            self.g['W?' + alias] = self.add_word(word, 'buzz')
        # Pseudo-nouns also occur as strings in room property records.
        for f in objects:
            for p in f.items[2:]:
                if name(p[0]) == 'PSEUDO':
                    for word in p[1::2]:
                        self.add_word(word.upper(), 'object')
        role_bits = {'object': 128, 'verb': 64, 'adjective': 32, 'direction': 16, 'preposition': 8, 'buzz': 4}
        role_first = {'preposition': 0, 'direction': 1, 'adjective': 2, 'verb': 3, 'object': 5}
        self.g.update({'PS?' + {'object': 'OBJECT', 'verb': 'VERB', 'adjective': 'ADJECTIVE', 'direction': 'DIRECTION', 'preposition': 'PREPOSITION', 'buzz': 'BUZZ-WORD'}[k]: v for k, v in role_bits.items()})
        self.g.update({'P1?' + k.upper(): v for k, v in role_first.items()})
        for key, ptr in self.dictionary.items():
            parts = self.word_parts[key]
            valued = [(k, v) for k, v in parts.items() if k not in ('object', 'buzz')]
            if len(valued) > 2:
                raise ValueError(f'Too many word roles: {key}: {parts}')
            self.memory[ptr + 4] = sum(role_bits[k] for k in parts) | (role_first[valued[0][0]] if valued else 0)
            for i, (_, value) in enumerate(valued):
                self.memory[ptr + 5 + i] = value
        # Build the exact eight-byte syntax records consumed by GPARSER.
        action_pre = {}
        verb_records = defaultdict(list)
        location_bits = {'HELD': 128, 'CARRIED': 64, 'IN-ROOM': 32, 'ON-GROUND': 16, 'TAKE': 8, 'MANY': 4, 'HAVE': 2}
        for s in syntax:
            eq = s.index(Atom('='))
            verb = name(s[0])
            action = name(s[eq + 1])
            if len(s) > eq + 2:
                action_pre[action] = name(s[eq + 2])
            count, prep, specs = 0, 0, []
            for a in s[1:eq]:
                if name(a) == 'OBJECT':
                    specs.append([prep, 0, 240])
                    count += 1
                    prep = 0
                elif isinstance(a, Atom):
                    prep = self.g['PR?' + a.name]
                elif name(a[0]) == 'FIND':
                    specs[-1][1] = self.g[name(a[1])]
                else:
                    specs[-1][2] = sum(location_bits[name(b)] for b in a)
            while len(specs) < 2:
                specs.append([prep, 0, 0])
                prep = 0
            verb_records[verb].append([count, specs[0][0], specs[1][0], specs[0][1], specs[1][1], specs[0][2], specs[1][2], actions.index(action)])
        pointers = []
        for verb in verbs:
            records = verb_records[verb]
            pointers.append(self.alloc(bytes([len(records)] + [x for record in records for x in record])))
        self.g['VERBS'] = self.alloc(b''.join(self.word(x) for x in pointers))
        self.g['ACTIONS'] = self.alloc(b''.join(self.word(self.g[a]) for a in actions))
        self.g['PREACTIONS'] = self.alloc(b''.join(self.word(self.g[action_pre[a]] if a in action_pre else 0) for a in actions))
        self.g['PREPOSITIONS'] = self.alloc(self.word(len(preps)) + b''.join(self.word(self.g['W?' + p]) + self.word(self.g['PR?' + p]) for p in preps))
        for symbol in self.global_defs:
            self.resolve(symbol)
        for key, default in (('SIZE', 5), ('CAPACITY', 0), ('VALUE', 0), ('TVALUE', 0)):
            self.defaults[self.g['P?' + key]] = default
        for f in objects:
            obj_id = self.g[name(f.items[1])]
            obj = self.objects[obj_id]
            for p in f.items[2:]:
                key, *args = p
                key = name(key)
                if key == 'IN' and len(args) == 1:
                    obj['parent'] = self.g[name(args[-1])]
                    continue
                if key == 'DESC':
                    obj['description'] = args[0]
                    continue
                if key == 'FLAGS':
                    obj['flags'] = [self.g[name(a)] for a in args]
                    continue
                if key in [name(d) for d in self.directions]:
                    if isinstance(args[0], str):
                        data = self.word(self.string(args[0]))
                    elif name(args[0]) == 'PER':
                        data = self.word(self.g[name(args[1])]) + b'\x00'
                    elif len(args) == 2:
                        data = bytes([self.g[name(args[1])]])
                    else:
                        dest, flag = name(args[1]), name(args[3])
                        message = self.string(args[args.index(Atom('ELSE')) + 1]) if Atom('ELSE') in args else 0
                        if flag in self.global_names:
                            data = bytes([self.g[dest], self.global_names.index(flag) + 16]) + self.word(message)
                        else:
                            data = bytes([self.g[dest], self.g[flag]]) + self.word(message) + b'\x00'
                elif key == 'SYNONYM':
                    data = b''.join(self.word(self.g['W?' + name(a)]) for a in args)
                elif key == 'ADJECTIVE':
                    data = bytes(self.g['A?' + name(a)] for a in args)
                elif key == 'GLOBAL':
                    data = bytes(self.g[name(a)] for a in args)
                elif key == 'PSEUDO':
                    data = b''.join(self.word(self.g['W?' + args[i].upper()]) + self.word(self.g[name(args[i + 1])]) for i in range(0, len(args), 2))
                else:
                    data = b''.join(self.word(self.evaluate(a)) for a in args)
                ptr = self.alloc(data)
                self.sizes[ptr] = len(data)
                obj['properties'][self.g['P?' + key]] = ptr
        for obj_id, obj in self.objects.items():
            if obj['parent']:
                self.objects[obj['parent']]['children'].insert(0, obj_id)
        self.memory[2:4] = self.word(119)
        self.memory[18:24] = b'880429'


def main():
    entry = read_file(SOURCE_ROOT / 'zork1.zil')
    includes = [f.items[1].lower() for f in entry if head(f) == 'INSERT-FILE']
    if includes != list(SOURCES):
        raise ValueError('The entrypoint include graph changed; update SOURCES before translating')
    forms = list(source_forms(SOURCE_ROOT))
    builder = Builder(forms)
    builder.build()
    DEST.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    for symbol, (source, form) in builder.routines.items():
        grouped[source].append(Compiler(builder).routine(form))
    for source, routines in grouped.items():
        code = ('# Generated by tools/translate.py; edit the translator or the ZIL source.\n'
                'from ..runtime import BlockAgain, BlockReturn, RoutineReturn, Restart\n\n\n' + '\n\n'.join(routines))
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == 'g' and isinstance(node.slice, ast.Constant)
                    and node.slice.value not in builder.g):
                raise ValueError(f'Unresolved generated reference: {node.slice.value}')
        (DEST / f'{"z" if source[0].isdigit() else ""}{source}.py').write_text(code, encoding='utf-8', newline='\n')
    imports = '\n'.join(f'from . import {"z" if s[0].isdigit() else ""}{s}' for s in grouped)
    registry = ',\n'.join(f'    {builder.g[n]}: {"z" if s[0].isdigit() else ""}{s}.{identifier(n)}' for n, (s, _) in builder.routines.items())
    (DEST / '__init__.py').write_text(f'"""Complete translated Zork I routine registry."""\n{imports}\n\nROUTINES = {{\n{registry}\n}}\n', encoding='utf-8', newline='\n')
    hashes = {f'{s}.zil': hashlib.sha256((SOURCE_ROOT / f'{s}.zil').read_text(encoding='utf-8').encode()).hexdigest() for s in ('zork1', *SOURCES)}
    image = {'globals': builder.g, 'memory': builder.memory.hex(), 'strings': builder.strings,
             'objects': builder.objects, 'sizes': builder.sizes, 'defaults': builder.defaults,
             'dictionary': builder.dictionary, 'globals_by_number': builder.globals_by_number,
             'source_hashes': hashes}
    (DEST / 'world.json').write_text(json.dumps(image, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    manifest = {'routines': {n: {'source': s + '.zil', 'python': identifier(n)} for n, (s, _) in builder.routines.items()},
                'rooms': sum(head(f) == 'ROOM' for _, f in forms), 'objects': len(builder.objects),
                'syntax_rules': sum(head(f) == 'SYNTAX' for _, f in forms),
                'dictionary_entries': len(builder.dictionary), 'source_hashes': hashes}
    manifest['artifact_hashes'] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(DEST.iterdir()) if p.suffix == '.py' or p.name == 'world.json'
    }
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'Translated {len(builder.routines)} routines, {len(builder.objects)} objects, '
          f'{manifest["syntax_rules"]} syntax rules; data size {len(builder.memory)} bytes.')


if __name__ == '__main__':
    main()
