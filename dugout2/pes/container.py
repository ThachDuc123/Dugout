"""The compressed block inside the save's data that holds the career player table.

    outer header   u32 LE container length, u32 LE length of the bytes after it, 8 zero bytes
    sub header     20 11 09 12, 4 zero bytes, u32 BE total raw size, u32 BE total compressed size
    chunks         u32 BE raw size, u32 BE compressed size, u32 BE end offset (from the sub header,
                   0 on the last chunk), then one zlib stream of up to 256 KB of raw data

A change is written back by recompressing only the chunks it touches to exactly their old
compressed size, so every other byte of the save stays where it was.
"""
import re
import struct
import zlib
from dataclasses import dataclass

MAGIC = b'\x20\x11\x09\x12\x00\x00\x00\x00'
CHUNK_HEADER = 12


class ContainerError(ValueError):
    pass


@dataclass
class Chunk:
    header: int        # offset of the chunk header in the data block
    stream: int        # offset of the zlib stream
    comp: int          # compressed size
    raw: int           # raw size
    raw_start: int     # offset of this chunk's bytes in the inflated table


def locate(data):
    """The chunks of the container, checked against their headers and the totals."""
    at = data.find(MAGIC)
    while at >= 0:
        chunks = _parse(data, at)
        if chunks:
            return chunks
        at = data.find(MAGIC, at + 1)
    raise ContainerError('compressed career block not found')


def _parse(data, sub):
    try:
        raw_total, comp_total = struct.unpack_from('>II', data, sub + 8)
    except struct.error:
        return None
    pos, raw_start, chunks = sub + 16, 0, []
    while raw_start < raw_total:
        if pos + CHUNK_HEADER > len(data):
            return None
        raw, comp, end = struct.unpack_from('>III', data, pos)
        if not 0 < raw <= 0x40000 or not 0 < comp <= len(data) - pos - CHUNK_HEADER:
            return None
        stream = pos + CHUNK_HEADER
        if data[stream] != 0x78:
            return None
        chunks.append(Chunk(pos, stream, comp, raw, raw_start))
        raw_start += raw
        pos = stream + comp
        if end and end != pos - sub:
            return None
    if raw_start != raw_total or sum(c.comp for c in chunks) != comp_total:
        return None
    return chunks


def inflate(data, chunks=None):
    chunks = chunks or locate(data)
    out = []
    for c in chunks:
        raw = zlib.decompress(data[c.stream:c.stream + c.comp])
        if len(raw) != c.raw:
            raise ContainerError('chunk size mismatch')
        out.append(raw)
    return b''.join(out)


def inflate_any(data):
    """Every zlib stream found in the data, joined (the way the career table has always been read);
    used when the container layout is not recognised."""
    try:
        return inflate(data)
    except (ContainerError, zlib.error):
        pass
    streams, cursor = [], 0
    pat = re.compile(rb'x[\x01\x9c\xda]')
    while cursor < len(data) - 2:
        m = pat.search(data, cursor)
        if not m:
            break
        start = m.start()
        d = zlib.decompressobj()
        try:
            out = d.decompress(memoryview(data)[start:])
            if not d.eof:
                raise zlib.error('incomplete stream')
        except zlib.error:
            cursor = start + 1
            continue
        streams.append(out)
        cursor = start + (len(data) - start - len(d.unused_data))
    return b''.join(streams)


def compress_exact(raw, size, level_byte=0xDA):
    """A zlib stream of `raw` exactly `size` bytes long, or None.

    Compresses the start of the block and keeps the last `n` bytes in a stored (uncompressed)
    deflate block; each stored byte costs about one byte more, so trying n = 0, 1, 2... walks the
    total length up one byte at a time until it matches. Empty stored blocks (5 bytes) help too."""
    adler = struct.pack('>I', zlib.adler32(raw))
    header = bytes([0x78, level_byte])
    best = None
    for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED):
        for mem in (9, 8):
            for n in range(0, 4096):
                if n > len(raw):
                    break
                c = zlib.compressobj(9, zlib.DEFLATED, -15, mem, strategy)
                body = c.compress(raw[:len(raw) - n]) + c.flush(zlib.Z_SYNC_FLUSH)
                tail = raw[len(raw) - n:]
                stored = _stored_blocks(tail, final=True)
                total = 2 + len(body) + len(stored) + 4
                if total == size:
                    stream = header + body + stored + adler
                    if zlib.decompress(stream) == raw:
                        return stream
                if total > size:
                    # 5-byte empty stored blocks before the tail can fill a gap of 5, 10, ...
                    break
                gap = size - total
                if gap % 5 == 0 and gap <= 50:
                    stream = header + body + b'\x00\x00\x00\xff\xff' * (gap // 5) + stored + adler
                    if len(stream) == size and zlib.decompress(stream) == raw:
                        best = stream
                        return best
    return best


def _stored_blocks(data, final):
    """Raw deflate stored blocks of `data` (byte-aligned stream expected), the last one final."""
    out = bytearray()
    if not data:
        return bytes([1 if final else 0]) + b'\x00\x00\xff\xff'
    for i in range(0, len(data), 65535):
        part = data[i:i + 65535]
        last = final and i + 65535 >= len(data)
        out += bytes([1 if last else 0]) + struct.pack('<HH', len(part), len(part) ^ 0xFFFF) + part
    return bytes(out)


def replace(data, chunks, new_table):
    """The data block with the inflated table replaced by `new_table` (same length). Only the
    chunks whose bytes changed are recompressed, each to its old compressed size."""
    old_table = inflate(data, chunks)
    if len(new_table) != len(old_table):
        raise ContainerError('the table must keep its length')
    out = bytearray(data)
    changed = []
    for c in chunks:
        new_raw = new_table[c.raw_start:c.raw_start + c.raw]
        if new_raw == old_table[c.raw_start:c.raw_start + c.raw]:
            continue
        stream = compress_exact(new_raw, c.comp, data[c.stream + 1])
        if stream is None:
            raise ContainerError('could not recompress a chunk to its original size')
        out[c.stream:c.stream + c.comp] = stream
        changed.append(c)
    return bytes(out), changed
