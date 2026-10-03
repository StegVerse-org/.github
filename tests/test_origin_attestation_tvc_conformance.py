"""The attestation exchange, against TV/TVC's own signing functions.

`tests/test_origin_attestation.py` holds the binding to its contract using a
stand-in that reproduces the authority's *receipt* shape. That is the right
default, because the authority's algorithm is not this repository's to carry and
a stand-in cannot drift into one. But a contract held only against a stand-in is
a contract held against this repository's belief about the authority.

This module closes that by running the exchange against the real functions:

    StegVerse-Labs/tvc:scripts/tv_credential_sign_export_resident.py
    StegVerse-Labs/tvc:scripts/tv_credential_verify_export_resident.py

`StegVerse-Labs/tvc` is a different organization, and a cross-organization
checkout in this repository's CI needs a credential while
`github_token_runtime_authority` is NONE. So this module **skips** when TVC is
not present, and the skip is loud rather than silent: a skipped conformance run
is reported as unproven, never as passed. Point `STEGVERSE_TVC_ROOT` at a TVC
checkout to run it, which is what makes it runnable from TVC's own CI -- where
it belongs, because TVC's source-validation receipt records
`tv_consumer_integration_observed: false` -- which it no longer does, because
this consumer is now observed there against those functions as of
`StegVerse-Labs/tvc@1e6c909`. The module stays here because a skip in this CI
must keep reporting what this CI did not prove.

The key is a test key, exactly as TVC's own `test_tv_credential_signing.py`
passes one. The production key is loaded from a systemd credential directory on
a TV/TVC resident host, is never persisted and has no development fallback, so
no key used here can be the production key.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNER = "scripts/tv_credential_sign_export_resident.py"
VERIFIER = "scripts/tv_credential_verify_export_resident.py"

#: The same test key TVC's own signing test uses.
TEST_KEY = b"tvc-test-signing-key"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


attestation = _module("origin_attestation", ROOT / "org-boundary/runtime/origin_attestation.py")
kernel = _module("org_kernel", ROOT / "org-kernel/kernel.py")


def tvc_root():
    """Where a TVC checkout is, or None. Declared, never guessed from a host."""
    declared = os.environ.get("STEGVERSE_TVC_ROOT")
    candidates = [Path(declared)] if declared else []
    candidates += [ROOT.parent / "tvc", ROOT.parent / "TVC"]
    for candidate in candidates:
        if (candidate / SIGNER).is_file() and (candidate / VERIFIER).is_file():
            return candidate
    return None


TVC = tvc_root()
REASON = ("TV/TVC is not checked out; set STEGVERSE_TVC_ROOT to run the "
          "conformance exchange. A skipped run is unproven, not passed.")


@unittest.skipUnless(TVC, REASON)
class TvcConformanceTests(unittest.TestCase):
    """What this repository believes about the authority, held to the authority."""

    @classmethod
    def setUpClass(cls):
        cls.signer = _module("tv_signer", TVC / SIGNER)
        cls.verifier = _module("tv_verifier", TVC / VERIFIER)
        cls.authority = {
            "sign": functools.partial(cls.signer.sign_export, key=TEST_KEY),
            "verify": functools.partial(cls.verifier.verify_export, key=TEST_KEY),
        }

    def statement(self, **overrides):
        body = {"origin_organization": "StegVerse-org",
                "destination_organization": "StegVerse-Labs",
                "destination_service": "stegverse-labs.sdk-manifest-ingress",
                "packet_id": "tvc-conformance-1",
                "payload_sha256": kernel.sha({"probe": True}),
                "transport_profile": "stegverse.intr.org-boundary.v1"}
        body.update(overrides)
        return attestation.statement(**body)

    # --- the exchange ------------------------------------------------------

    def test_the_authority_signs_and_verifies_this_boundarys_statement(self):
        declared = self.statement()
        signature, receipt = attestation.attest(declared, self.authority)
        self.assertEqual(signature["algo"], attestation.ALGORITHM)
        self.assertEqual(receipt["operation"], attestation.VERIFY_OPERATION)
        self.assertEqual(receipt["credential_authority"], attestation.CREDENTIAL_AUTHORITY)
        self.assertIs(receipt["signature_valid"], True)

    def test_this_boundarys_signature_serialization_is_the_authoritys(self):
        """TVC digests the artifact as `json.dumps(indent=2, sort_keys=True)`.

        A different serialization of the same object is a different artifact, so
        a mismatch here would make every signature_sha256 in our records wrong
        while the signature itself still verified.
        """
        declared = self.statement()
        signature, _ = self.signer.sign_export(
            payload=attestation.payload_bytes(declared), key=TEST_KEY)
        self.assertEqual(
            attestation.canon_signature(signature),
            json.dumps(signature, indent=2, sort_keys=True).encode("utf-8"))

    def test_the_authority_refuses_a_statement_it_did_not_sign(self):
        declared = self.statement()
        signature, _ = attestation.attest(declared, self.authority)
        for field, value in (("origin_organization", "StegVerse-Labs"),
                             ("packet_id", "another-packet"),
                             ("payload_sha256", kernel.sha({"evil": True})),
                             ("destination_organization", "StegGhost"),
                             ("destination_service", "stegghost.org-control"),
                             ("transport_profile", "something.else.v1")):
            with self.subTest(field=field):
                with self.assertRaises(attestation.AttestationRefused) as refused:
                    attestation.verify(self.statement(**{field: value}),
                                       signature, self.authority["verify"])
                self.assertEqual(refused.exception.failed_predicate,
                                 "STATEMENT_MATCHES_WHAT_THE_AUTHORITY_SIGNED")

    def test_without_the_key_the_signature_does_not_verify(self):
        declared = self.statement()
        signature, _ = attestation.attest(declared, self.authority)
        forger = functools.partial(self.verifier.verify_export, key=b"a-forgers-key")
        with self.assertRaises(attestation.AttestationRefused) as refused:
            attestation.verify(declared, signature, forger)
        self.assertEqual(refused.exception.failed_predicate,
                         "CREDENTIAL_AUTHORITY_REPORTS_THE_SIGNATURE_VALID")

    # --- what the authority's own receipts assert --------------------------

    def test_the_authority_exposes_no_key_material_in_its_receipts(self):
        declared = self.statement()
        signature, sign_receipt = self.signer.sign_export(
            payload=attestation.payload_bytes(declared), key=TEST_KEY)
        verify_receipt = self.verifier.verify_export(
            payload=attestation.payload_bytes(declared),
            signature_bytes=attestation.canon_signature(signature), key=TEST_KEY)
        for receipt in (sign_receipt, verify_receipt):
            self.assertIs(receipt["credential_value_exposed"], False)
            self.assertIs(receipt["key_material_persisted"], False)
            self.assertIs(receipt["github_actions_authority"], False)
            self.assertNotIn(TEST_KEY.decode(), json.dumps(receipt))
        self.assertIs(sign_receipt["fallback_key_used"], False)

    def test_the_authority_fails_closed_on_an_empty_key_or_payload(self):
        with self.assertRaises(ValueError):
            self.signer.sign_export(payload=b"x", key=b"")
        with self.assertRaises(ValueError):
            self.signer.sign_export(payload=b"", key=TEST_KEY)


class ConformanceIsReportedTests(unittest.TestCase):
    """A skip must be visible as unproven rather than absent."""

    def test_the_skip_reason_says_a_skipped_run_is_unproven(self):
        self.assertIn("unproven", REASON)

    def test_the_authority_source_this_boundary_declares_is_the_one_run_here(self):
        self.assertTrue(attestation.AUTHORITY_SOURCE.startswith("StegVerse-Labs/tvc:"))
        self.assertIn(VERIFIER, attestation.AUTHORITY_SOURCE)


if __name__ == "__main__":
    unittest.main()
