"""Pure-Python crypto used for Web Push, checked against published test vectors."""

import hashlib
import json
import os

import pytest
from ecdsa import NIST256p, SigningKey, VerifyingKey
from ecdsa.util import sigdecode_string

from gccpro import aesgcm, push
from gccpro.push import b64url_decode


def test_aes_fips197_vector():
    # FIPS 197, appendix C.1 (AES-128).
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    block = bytes.fromhex("00112233445566778899aabbccddeeff")
    out = aesgcm.encrypt_block(aesgcm.expand_key(key), block)
    assert out.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"


def test_gcm_nist_vectors():
    # McGrew & Viega GCM spec, test cases 1 and 2.
    assert aesgcm.encrypt(bytes(16), bytes(12), b"").hex() == "58e2fccefa7e3061367f1d57a4e7455a"
    assert aesgcm.encrypt(bytes(16), bytes(12), bytes(16)).hex() == (
        "0388dace60b6a392f328c2b971b2fe78" "ab6e47d42cec13bdf53a67b21257bddf"
    )
    # Test case 3: multi-block plaintext with a non-zero key and nonce.
    key = bytes.fromhex("feffe9928665731c6d6a8f9467308308")
    nonce = bytes.fromhex("cafebabefacedbaddecaf888")
    plaintext = bytes.fromhex(
        "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
        "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b391aafd255"
    )
    assert aesgcm.encrypt(key, nonce, plaintext).hex() == (
        "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091473f5985"
        "4d5c2af327cd64a62cf35abd2ba6fab4"
    )


def test_gcm_matches_reference_implementation():
    reference = pytest.importorskip("cryptography.hazmat.primitives.ciphers.aead")
    for length in [0, 1, 15, 16, 17, 31, 32, 33, 100, 255]:
        key, nonce, plaintext = os.urandom(16), os.urandom(12), os.urandom(length)
        expected = reference.AESGCM(key).encrypt(nonce, plaintext, None)
        assert aesgcm.encrypt(key, nonce, plaintext) == expected, length


def test_rfc8291_example():
    # RFC 8291, section 5 (and appendix A intermediate values).
    as_private = SigningKey.from_string(
        b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), curve=NIST256p
    )
    body = push.encrypt(
        b"When I grow up, I want to be a watermelon",
        b64url_decode("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
        b64url_decode("BTBZMqHH6r4Tts7J_aSIgg"),
        as_private=as_private,
        salt=b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
    )
    assert push.b64url_encode(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A"
        "_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_vapid_header_verifies():
    private = push.generate_vapid_private_key()
    header = push.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", private,
                                      "mailto:a@b.fr", now=1_000_000)
    token = header.split("t=")[1].split(",")[0]
    key = header.split("k=")[1]
    head, claims, signature = token.split(".")
    assert json.loads(b64url_decode(claims)) == {
        "aud": "https://fcm.googleapis.com", "exp": 1_000_000 + push.TTL, "sub": "mailto:a@b.fr",
    }
    verifier = VerifyingKey.from_string(b64url_decode(key), curve=NIST256p)
    assert verifier.verify(b64url_decode(signature), f"{head}.{claims}".encode(),
                           hashfunc=hashlib.sha256, sigdecode=sigdecode_string)
