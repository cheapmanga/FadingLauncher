"""
GVAS parser/serializer for Fading Echo (UE 5.6.1 / project UE_YGRO).

Verified layout (UE 5.6 FPropertyTag with FPropertyTypeName):
  Header: 'GVAS' | SaveGameVersion i32 | PkgVerUE4 i32 | PkgVerUE5 i32
          | EngineMajor u16 | Minor u16 | Patch u16 | Changelist u32
          | Branch FString | CustomVersionFormat i32 | CustomVersionCount i32
          | CustomVersion[Count] (16-byte GUID + i32) | SaveGameClassName FString
  Body:   sequence of property tags:
          Name FString | TypeName (FString + i32 nParams + nParams recursive TypeNames)
          | Size i32 | Flags u8 | Data[Size]
          terminated by a tag whose Name == 'None'.

Inter-object framing between SaveTreeEntry blocks is NOT fully reversed; it is
captured verbatim as opaque 'gap' bytes so that round-tripping is byte-exact.
"""
import struct

class R:
    def __init__(s, d, o=0): s.d, s.o = d, o
    def i32(s):
        v = struct.unpack_from('<i', s.d, s.o)[0]; s.o += 4; return v
    def u32(s):
        v = struct.unpack_from('<I', s.d, s.o)[0]; s.o += 4; return v
    def u8(s):
        v = s.d[s.o]; s.o += 1; return v
    def raw(s, n):
        v = s.d[s.o:s.o+n]; s.o += n; return v
    def fstring(s):
        n = s.i32()
        if n == 0: return ''
        if n < 0:
            if s.o - 2*n > len(s.d): raise ValueError('utf16 string overruns buffer')
            b = s.raw(-2*n); return b[:-2].decode('utf-16-le', 'replace')
        if n > 1 << 20 or s.o + n > len(s.d): raise ValueError('string overruns buffer')
        b = s.raw(n); return b[:-1].decode('utf-8', 'replace')

def w_fstring(v):
    if v == '': return struct.pack('<i', 0)
    try:
        b = v.encode('ascii') + b'\x00'
        return struct.pack('<i', len(b)) + b
    except UnicodeEncodeError:
        b = v.encode('utf-16-le') + b'\x00\x00'
        return struct.pack('<i', -(len(b)//2)) + b

class TypeName:
    __slots__ = ('name', 'params')
    def __init__(s, name, params): s.name, s.params = name, params
    def __str__(s):
        return s.name + ('<' + ','.join(str(p) for p in s.params) + '>' if s.params else '')
    def pack(s):
        out = w_fstring(s.name) + struct.pack('<i', len(s.params))
        for p in s.params: out += p.pack()
        return out

_VALID_TYPE_SUFFIX = 'Property'

def read_typename(r, depth=0):
    if depth > 8: raise ValueError('typename nesting too deep')
    nm = r.fstring()
    # A real UE type name is a short ascii identifier ending in 'Property'
    # (or a struct/package path passed as a type parameter).
    if not nm or len(nm) > 64 or not nm.isascii() or not nm.isprintable():
        raise ValueError('implausible type name %r' % nm[:40])
    n = r.i32()
    if not (0 <= n <= 8): raise ValueError('bad typename param count %d' % n)
    return TypeName(nm, [read_typename(r, depth+1) for _ in range(n)])

# EPropertyTagFlags (UE 5.4+)
TAG_HAS_ARRAY_INDEX          = 0x01
TAG_HAS_PROPERTY_GUID        = 0x02
TAG_HAS_PROPERTY_EXTENSIONS  = 0x04
TAG_HAS_BINARY_OR_NATIVE_SER = 0x08
TAG_BOOL_TRUE                = 0x10

class Prop:
    __slots__ = ('name', 'type', 'flags', 'data', 'offset')
    def __init__(s, name, type_, flags, data, offset):
        s.name, s.type, s.flags, s.data, s.offset = name, type_, flags, data, offset
    def pack(s):
        return (w_fstring(s.name) + s.type.pack()
                + struct.pack('<i', len(s.data)) + bytes([s.flags]) + s.data)
    @property
    def tname(s): return str(s.type)
    def set_bool(s, v):
        if s.type.name != 'BoolProperty':
            raise TypeError('%s is not a BoolProperty' % s.name)
        s.flags = (s.flags | TAG_BOOL_TRUE) if v else (s.flags & ~TAG_BOOL_TRUE)

    #: Types dont la valeur tient sur une largeur FIXE : les modifier ne change pas la
    #: taille du fichier, donc c'est sûr. Tout le reste (chaînes, tableaux, maps) casse
    #: le cadrage inter-objets, qui n'est pas rétro-conçu — on refuse.
    _FIXED_FMT = {'IntProperty': '<i', 'Int64Property': '<q',
                  'FloatProperty': '<f', 'DoubleProperty': '<d'}

    def editable(s):
        """Vrai si cette propriété peut être modifiée sans risque."""
        return s.type.name == 'BoolProperty' or s.type.name in s._FIXED_FMT \
            or (s.type.name == 'ByteProperty' and len(s.data) == 1)

    def set_value(s, v):
        """Écrit une valeur, uniquement pour les types à largeur fixe. Sûr = round-trip
        exact ; refuse les types dont l'édition casserait le fichier."""
        t = s.type.name
        if t == 'BoolProperty':
            s.set_bool(bool(v)); return
        if t in s._FIXED_FMT:
            new = struct.pack(s._FIXED_FMT[t], v)
            assert len(new) == len(s.data), 'largeur inattendue'
            s.data = new; return
        if t == 'ByteProperty' and len(s.data) == 1:
            s.data = bytes([int(v) & 0xFF]); return
        raise TypeError('%s (%s) : édition non supportée (casserait le fichier)'
                        % (s.name, t))

    def value(s):
        t = s.type.name
        if t == 'IntProperty':    return struct.unpack('<i', s.data)[0]
        if t == 'Int64Property':  return struct.unpack('<q', s.data)[0]
        if t == 'FloatProperty':  return struct.unpack('<f', s.data)[0]
        if t == 'DoubleProperty': return struct.unpack('<d', s.data)[0]
        if t == 'BoolProperty':
            # UE 5.4+: BoolProperty has Size==0; the value lives in the tag flags.
            return bool(s.flags & TAG_BOOL_TRUE)
        if t == 'ByteProperty':   return s.data[0] if len(s.data) == 1 else s.data
        if t in ('StrProperty', 'NameProperty', 'ObjectProperty', 'SoftObjectProperty'):
            return R(s.data).fstring()
        if t in ('ArrayProperty', 'SetProperty'):
            return struct.unpack_from('<I', s.data, 0)[0]
        if t == 'MapProperty':
            return struct.unpack_from('<I', s.data, 4)[0]
        return s.data

class Header:
    __slots__ = ('magic','save_ver','ue4','ue5','engine','changelist','branch',
                 'cv_format','custom_versions','class_name','size')
    def pack(s):
        out = b'GVAS' + struct.pack('<iii', s.save_ver, s.ue4, s.ue5)
        out += struct.pack('<HHH', *s.engine) + struct.pack('<I', s.changelist)
        out += w_fstring(s.branch)
        out += struct.pack('<ii', s.cv_format, len(s.custom_versions))
        for g, v in s.custom_versions: out += g + struct.pack('<i', v)
        out += w_fstring(s.class_name)
        return out

def read_header(r):
    h = Header()
    h.magic = r.raw(4)
    if h.magic != b'GVAS': raise ValueError('not a GVAS file: %r' % h.magic)
    h.save_ver, h.ue4, h.ue5 = r.i32(), r.i32(), r.i32()
    h.engine = struct.unpack_from('<HHH', r.d, r.o); r.o += 6
    h.changelist = r.u32()
    h.branch = r.fstring()
    h.cv_format = r.i32()
    n = r.i32()
    h.custom_versions = [(r.raw(16), r.i32()) for _ in range(n)]
    h.class_name = r.fstring()
    h.size = r.o
    return h

def _looks_like_tag(d, o):
    """Heuristic resync: does a valid Name+TypeName tag start at o?"""
    if o + 8 > len(d): return False
    try:
        n = struct.unpack_from('<i', d, o)[0]
        if not (2 <= n <= 512) or o + 4 + n > len(d): return False
        s = d[o+4:o+4+n]
        if s[-1] != 0: return False
        body = s[:-1]
        if not all(32 <= c < 127 for c in body): return False
        r = R(d, o); r.fstring(); tn = read_typename(r)
        return tn.name.endswith(_VALID_TYPE_SUFFIX)
    except Exception:
        return False

class Block:
    """A run of property tags, plus the opaque bytes that follow its None terminator."""
    __slots__ = ('props', 'term', 'gap', 'start')
    def __init__(s, props, term, gap, start):
        s.props, s.term, s.gap, s.start = props, term, gap, start
    def pack(s):
        return b''.join(p.pack() for p in s.props) + s.term + s.gap
    def get(s, name):
        for p in s.props:
            if p.name == name: return p
        return None

class Save:
    __slots__ = ('header', 'pad', 'blocks', 'tail', 'path')
    def pack(s):
        return s.header.pack() + s.pad + b''.join(b.pack() for b in s.blocks) + s.tail
    def all_props(s):
        for b in s.blocks:
            for p in b.props: yield p

def parse(data, path=None):
    r = R(data)
    sv = Save(); sv.path = path
    sv.header = read_header(r)
    # padding between header and first property tag (1 byte on UE_YGRO 5.6.1)
    p0 = r.o
    while r.o < len(data) - 8 and not _looks_like_tag(data, r.o):
        r.o += 1
    sv.pad = data[p0:r.o]
    sv.blocks = []
    while r.o < len(data) - 4:
        start = r.o
        props = []
        term = b''
        while True:
            if r.o >= len(data) - 4:
                break
            o0 = r.o
            try:
                name = r.fstring()
            except Exception:
                r.o = o0; break
            if name == 'None':
                term = data[o0:r.o]
                break
            if not name:
                r.o = o0; break
            try:
                tn = read_typename(r)
                if not tn.name.endswith(_VALID_TYPE_SUFFIX):
                    raise ValueError('not a property type: %s' % tn.name)
                size = r.i32(); flags = r.u8()
                if size < 0 or r.o + size > len(data):
                    raise ValueError('bad size')
                props.append(Prop(name, tn, flags, r.raw(size), o0))
            except Exception:
                r.o = o0; break
        # capture opaque framing bytes until the next real tag
        g0 = r.o
        while r.o < len(data) - 8 and not _looks_like_tag(data, r.o):
            r.o += 1
        gap = data[g0:r.o]
        if not props and not term:
            r.o = g0
            break
        sv.blocks.append(Block(props, term, gap, start))
    sv.tail = data[r.o:]
    return sv

def load(path):
    with open(path, 'rb') as f: return parse(f.read(), path)

if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        sv = load(p)
        raw = open(p, 'rb').read()
        ok = sv.pack() == raw
        print('%-70s blocks=%-5d props=%-6d roundtrip=%s'
              % (p.split('/')[-2][:68], len(sv.blocks), sum(len(b.props) for b in sv.blocks),
                 'OK' if ok else 'MISMATCH'))
