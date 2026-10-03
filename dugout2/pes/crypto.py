"""PES 2021 save encryption.

File layout: 320-byte header | 208-byte file header | description | logo | data | serial.

The header, once decrypted, holds SHA-512 of the four blocks (description, logo, data, serial) and
64 key bytes. Every part is XOR-ed with a keystream from MT19937 (seeded with init_by_array) mixed
with rotations, so encrypting is the same operation as decrypting. The block keys derive from the
header (hashes included): a changed block means new hashes, a new header and new keys for all
blocks, which `encrypt` takes care of.
"""
import hashlib
import struct
from dataclasses import dataclass

import numpy as np

HEADER_SIZE = 320
FILE_HEADER_SIZE = 208
MASTER_KEY = bytes.fromhex(
    '9061d866437724f892bab87121c76063f0919a7ded4780de51f5ddd108fe3284'
    'f5099200b23e889feb244305587600229bfeecf6500029d3427550b9ecd2f675')
_SHUFFLED_MASTER = b''.join(MASTER_KEY[i:i + 8][::-1] for i in range(0, 64, 8))


class SaveError(ValueError):
    pass


def _mt_words(key, count):
    """`count` raw outputs of MT19937 seeded by init_by_array with the 16 words of `key`."""
    rs = np.random.RandomState(np.frombuffer(key, dtype='<u4').astype(np.uint32))
    return rs._bit_generator.random_raw(count).astype(np.uint32)


def _rotl(x, n):
    return (x << np.uint32(n)) | (x >> np.uint32(32 - n))


def _rotr(x, n):
    return (x >> np.uint32(n)) | (x << np.uint32(32 - n))


def keystream(key, length):
    if len(key) != 64:
        raise SaveError('PES stream key must contain 64 bytes')
    words = (length + 3) // 4
    s = _mt_words(key, words + 4)
    masks = np.empty(words, dtype=np.uint32)
    c0, c1, c2, c3 = (int(v) for v in s[:4])
    m32 = 0xFFFFFFFF
    for i in range(min(4, words)):                   # the first words, before the mixing settles
        c4 = int(s[i + 4])
        masks[i] = c4 ^ c3 ^ c2 ^ c1 ^ c0
        c0 = ((c1 >> 15) | (c1 << 17)) & m32
        c1 = ((c2 << 11) | (c2 >> 21)) & m32
        c2 = ((c3 << 7) | (c3 >> 25)) & m32
        c3 = ((c4 >> 13) | (c4 << 19)) & m32
    if words > 4:
        i = np.arange(4, words)
        masks[4:] = s[i + 4] ^ _rotr(s[i + 3], 13) ^ _rotr(s[i + 2], 6) ^ _rotl(s[i + 1], 5) ^ _rotr(s[i], 10)
    return masks.astype('<u4').view(np.uint8)[:length]


def crypt(key, payload):
    if not payload:
        return b''
    buf = np.frombuffer(payload, dtype=np.uint8)
    return (buf ^ keystream(key, len(payload))).tobytes()


def _xor_u64(key, value):
    return b''.join(struct.pack('<Q', part ^ value) for part in struct.unpack('<8Q', key))


def _rolling_key(header):
    rk = bytearray(header[:64])
    for i, v in enumerate(header[64:320]):
        rk[i & 63] ^= v
    return bytes(rk)


@dataclass
class SaveFile:
    key: bytes              # the header's 64 key bytes (kept as they are)
    file_header: bytes      # decrypted 208-byte file header
    description: bytes
    logo: bytes
    data: bytes
    serial: bytes

    @property
    def file_type(self):
        return self.file_header[144:176].split(b'\0', 1)[0].decode('ascii', 'replace')

    @property
    def game_version(self):
        return self.file_header[176:208].split(b'\0', 1)[0].decode('ascii', 'replace')


def decrypt(payload):
    if len(payload) < HEADER_SIZE + FILE_HEADER_SIZE:
        raise SaveError('Save is too small to contain a PES 2021 header')
    enc = payload[:HEADER_SIZE]
    key = enc[256:320]
    header = bytearray(crypt(bytes(a ^ b for a, b in zip(key, _SHUFFLED_MASTER)), enc))
    header[256:320] = key
    rk = _rolling_key(header)
    cursor = HEADER_SIZE
    fh = crypt(_xor_u64(rk, FILE_HEADER_SIZE), payload[cursor:cursor + FILE_HEADER_SIZE])
    cursor += FILE_HEADER_SIZE
    data_size, logo_size, desc_size, serial_len = struct.unpack_from('<4I', fh, 64)
    sizes = (desc_size, logo_size, data_size, serial_len * 2)
    if any(s > len(payload) for s in sizes) or cursor + sum(sizes) > len(payload):
        raise SaveError('Decrypted PES header contains invalid block sizes')
    blocks = []
    for k, size in enumerate(sizes):
        blocks.append(crypt(_xor_u64(rk, k), payload[cursor:cursor + size]))
        cursor += size
    for k, b in enumerate(blocks):                  # the game's own integrity check
        if hashlib.sha512(b).digest() != bytes(header[64 * k:64 * (k + 1)]):
            raise SaveError('Save block %d does not match its SHA-512' % k)
    return SaveFile(bytes(key), fh, *blocks)


def encrypt(save):
    blocks = (save.description, save.logo, save.data, save.serial)
    if len(save.serial) % 2:
        raise SaveError('serial block must have an even length')
    header = bytearray(HEADER_SIZE)
    for k, b in enumerate(blocks):
        header[64 * k:64 * (k + 1)] = hashlib.sha512(b).digest()
    header[256:320] = save.key
    enc_header = bytearray(crypt(bytes(a ^ b for a, b in zip(save.key, _SHUFFLED_MASTER)), bytes(header)))
    enc_header[256:320] = save.key
    rk = _rolling_key(header)
    fh = bytearray(save.file_header)
    struct.pack_into('<4I', fh, 64, len(save.data), len(save.logo), len(save.description), len(save.serial) // 2)
    out = [bytes(enc_header), crypt(_xor_u64(rk, FILE_HEADER_SIZE), bytes(fh))]
    for k, b in enumerate(blocks):
        out.append(crypt(_xor_u64(rk, k), b))
    return b''.join(out)


def read(path):
    with open(path, 'rb') as f:
        return decrypt(f.read())
