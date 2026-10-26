"""Tamper-evident audit log: hash chain + HMAC-SHA256 signatures + Merkle root.

entry_hash_i = SHA256(prev_hash || canonical_json(payload_i))
signature_i  = HMAC(key, entry_hash_i)            (if a key is supplied)
Any edit, deletion or reorder of an entry breaks verify(). The Merkle root
commits to the whole log in 32 bytes and can be anchored externally.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return hashlib.sha256(b"").hexdigest()
    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256((level[i] + level[i + 1]).encode()).hexdigest()
            for i in range(0, len(level), 2)
        ]
    return level[0]


@dataclass
class ChainEntry:
    index: int
    prev_hash: str
    payload: dict[str, Any]
    hash: str
    signature: str | None


class HashChain:
    GENESIS = "0" * 64

    def __init__(self, key: bytes | None = None) -> None:
        self.key = key
        self.entries: list[ChainEntry] = []

    def _hash(self, prev: str, payload: dict[str, Any]) -> str:
        return hashlib.sha256((prev + canonical(payload)).encode()).hexdigest()

    def _sign(self, h: str) -> str | None:
        return hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest() if self.key else None

    def append(self, payload: dict[str, Any]) -> ChainEntry:
        prev = self.entries[-1].hash if self.entries else self.GENESIS
        h = self._hash(prev, payload)
        entry = ChainEntry(len(self.entries), prev, dict(payload), h, self._sign(h))
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        prev = self.GENESIS
        for i, e in enumerate(self.entries):
            if e.index != i or e.prev_hash != prev or e.hash != self._hash(prev, e.payload):
                return False
            if self.key and not hmac.compare_digest(e.signature or "", self._sign(e.hash) or ""):
                return False
            prev = e.hash
        return True

    def root(self) -> str:
        return merkle_root([e.hash for e in self.entries])
