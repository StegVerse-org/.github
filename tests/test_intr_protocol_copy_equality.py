"""C6: the InTr protocol v1 contract is one byte sequence in every organization that carries it.

PORTED_COMPONENT_BYTES_EQUAL_ACROSS_ORGS. StegVerse-org/.github and StegVerse-Labs/.github
carry this same file and the same two pins; a copy whose bytes differ fails here with the
six fields, on the push or pull request that changes it. Offline: no clock, network or
credential is read. Lowest supported mode: E0 (a deterministic digest comparison).
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "data/intr-protocol/v1/protocol.json": "2c5a44d01508284caab062629c70685bd1bcdf84a89573fbdbbfc45095b49fb7",
    "org-runtime/intr_protocol.py": "2fe0dbbca71a9800714c587863050134383e636ad6d4976381dfe1c395298c61",
}
CARRIERS = ("StegVerse-org/.github", "StegVerse-Labs/.github")


class IntrProtocolCopyEquality(unittest.TestCase):
    def test_every_ported_file_matches_its_pin(self):
        for rel, pinned in PINS.items():
            actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            with self.subTest(path=rel):
                self.assertEqual(actual, pinned, {
                    "disposition": "FAIL_CLOSED",
                    "failure_code": "PORTED_COPY_DIGEST_MISMATCH",
                    "failed_predicate": "PORTED_COMPONENT_BYTES_EQUAL_ACROSS_ORGS",
                    "required_evidence_or_repair": "carry the same bytes of " + rel + " in " + " and ".join(CARRIERS)
                                                   + " and move both pins in one change per carrier",
                    "retry_entrypoint": "python -m unittest tests.test_intr_protocol_copy_equality",
                    "owning_existing_goal": "INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001 (StegVerse-org/.github#162)",
                    "next_attempt": "the next push or pull request that touches " + rel,
                    "observed_sha256": actual,
                })


if __name__ == "__main__":
    unittest.main()
