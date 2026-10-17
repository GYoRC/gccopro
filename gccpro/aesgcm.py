"""Minimal pure-Python AES-128-GCM encryption (FIPS 197 + NIST SP 800-38D).

Exists because the `cryptography` package has no wheel for the NAS (32-bit ARM,
glibc 2.26). It is only used to encrypt small Web Push payloads, so it favours
clarity over speed and implements encryption only. It is not hardened against
timing side channels, which is acceptable for this use: the key is a one-off
content key derived per message.
"""


def _xtime(byte: int) -> int:
    """Multiply a byte by x (i.e. 2) in AES's GF(2^8)."""
    byte <<= 1
    return (byte ^ 0x11B) if byte & 0x100 else byte


def _build_sbox() -> list[int]:
    """Compute the AES S-box (multiplicative inverse followed by the affine map)."""
    def rotl8(x: int, shift: int) -> int:
        return ((x << shift) | (x >> (8 - shift))) & 0xFF

    sbox = [0] * 256
    p = q = 1
    while True:
        # p walks the field multiplying by 3; q walks it dividing by 3, so q = 1/p.
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        sbox[p] = q ^ rotl8(q, 1) ^ rotl8(q, 2) ^ rotl8(q, 3) ^ rotl8(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


SBOX = _build_sbox()


def expand_key(key: bytes) -> list[list[int]]:
    """Expand a 16-byte AES-128 key into the 11 round keys (16 bytes each)."""
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16-byte key")
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]           # RotWord
            temp = [SBOX[b] for b in temp]       # SubWord
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], temp)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(11)]


def encrypt_block(round_keys: list[list[int]], block: bytes) -> bytes:
    """Encrypt one 16-byte block. State byte i is row i % 4, column i // 4."""
    state = [b ^ k for b, k in zip(block, round_keys[0])]
    for rnd in range(1, 11):
        state = [SBOX[b] for b in state]
        # ShiftRows: row r rotates left by r columns.
        state = [state[((i // 4 + i % 4) % 4) * 4 + i % 4] for i in range(16)]
        if rnd != 10:
            # MixColumns on each column (a0..a3).
            mixed = []
            for col in range(4):
                a0, a1, a2, a3 = state[4 * col:4 * col + 4]
                mixed += [
                    _xtime(a0) ^ _xtime(a1) ^ a1 ^ a2 ^ a3,
                    a0 ^ _xtime(a1) ^ _xtime(a2) ^ a2 ^ a3,
                    a0 ^ a1 ^ _xtime(a2) ^ _xtime(a3) ^ a3,
                    _xtime(a0) ^ a0 ^ a1 ^ a2 ^ _xtime(a3),
                ]
            state = mixed
        state = [b ^ k for b, k in zip(state, round_keys[rnd])]
    return bytes(state)


_R = 0xE1 << 120  # GCM reduction polynomial, in GCM's reflected bit order


def _gf_mult(x: int, y: int) -> int:
    """Multiply two 128-bit blocks in GF(2^128) as defined by GCM (bit 0 = MSB)."""
    z, v = 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ _R if v & 1 else v >> 1
    return z


def _ghash(h: int, data: bytes) -> int:
    """GHASH over ``data``, which must already be a multiple of 16 bytes."""
    y = 0
    for i in range(0, len(data), 16):
        y = _gf_mult(y ^ int.from_bytes(data[i:i + 16], "big"), h)
    return y


def encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """AES-128-GCM encrypt with a 12-byte nonce and no associated data.

    Returns:
        The ciphertext followed by the 16-byte authentication tag.
    """
    if len(nonce) != 12:
        raise ValueError("GCM nonce must be 12 bytes")
    round_keys = expand_key(key)
    h = int.from_bytes(encrypt_block(round_keys, bytes(16)), "big")
    j0 = nonce + b"\x00\x00\x00\x01"

    # CTR mode starting at inc32(J0).
    out = bytearray()
    counter = 1
    for i in range(0, len(plaintext), 16):
        counter += 1
        keystream = encrypt_block(round_keys, nonce + counter.to_bytes(4, "big"))
        chunk = plaintext[i:i + 16]
        out += bytes(a ^ b for a, b in zip(chunk, keystream))
    ciphertext = bytes(out)

    # Tag = E(K, J0) xor GHASH(C padded || len(A) || len(C)), lengths in bits.
    padded = ciphertext + bytes(-len(ciphertext) % 16)
    lengths = (0).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")
    s = _ghash(h, padded + lengths)
    tag = (int.from_bytes(encrypt_block(round_keys, j0), "big") ^ s).to_bytes(16, "big")
    return ciphertext + tag
