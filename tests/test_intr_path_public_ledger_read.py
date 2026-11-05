"""The public-ledger route of the cross-org read (E0, no credential): a carried source receipt verified on an
anonymously readable source ledger. (Identical in StegVerse-org/.github and StegVerse-Labs/.github.)

Deterministic and offline: the "anonymous copy" is a temporary bare repository built from this repository's
committed inbound row (.stegverse/intr-path-transfer/inbound.json), whose carried source receipts are byte-for-value
copies of the authentic, sealed receipts on the source ledger. The copy's HEAD.json names the carried organization
receipt, so the chain is that one sealed receipt. Fixed commit dates; no network, clock or credential. The live
anonymous fetch and dry run against the real source ledger are the validation workflow's public-ledger step.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOUND = json.loads((ROOT / ".stegverse/intr-path-transfer/inbound.json").read_text(encoding="utf-8"))
ROW = INBOUND["transfers"][0]
PID, CID = ROW["path_id"], ROW["communication_id"]
SOURCE_ORG, DESTINATION_ORG = PID.split(":")[0].split("->")
SOURCE_REPOSITORY = SOURCE_ORG + "/.github"
ORG_RECEIPT = ROW["carried"]["source_organization_receipt"]
REPO_RECEIPT = ROW["carried"]["source_repository_receipt"]
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
FIXED = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@invalid", "GIT_AUTHOR_DATE": "@0 +0000",
         "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@invalid", "GIT_COMMITTER_DATE": "@0 +0000"}


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pi = load("intr_path_ingress_public_route", "resident-runtime/intr_path_ingress.py")


def _git(bare: Path, *args: str, data: bytes | None = None) -> str:
    env = {**os.environ, **FIXED}
    return subprocess.run(["git", "--git-dir=" + str(bare), *args], input=data, capture_output=True,
                          check=True, env=env).stdout.decode().strip()


def build_copy(root: Path) -> str:
    """A bare <SOURCE_ORG>.git whose ledger ref holds HEAD.json -> the carried receipts. Returns the tip."""
    bare = root / (SOURCE_ORG + ".git")
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    def blob(doc) -> str:
        return _git(bare, "hash-object", "-w", "--stdin", data=(json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())

    def tree(entries: dict[str, str]) -> str:
        lines = "".join(("100644 blob " if kind == "blob" else "040000 tree ") + sha + "\t" + name + "\n"
                        for name, (kind, sha) in sorted(entries.items()))
        return _git(bare, "mktree", data=lines.encode())

    org_key = ORG_RECEIPT["receipt_sha256"].split(":", 1)[1] + ".json"
    repo_key = REPO_RECEIPT["receipt_sha256"].split(":", 1)[1] + ".json"
    repo_tree = tree({"receipts": ("tree", tree({repo_key: ("blob", blob(REPO_RECEIPT))}))})
    top = tree({
        "HEAD.json": ("blob", blob({"receipt_sha256": ORG_RECEIPT["receipt_sha256"]})),
        "receipts": ("tree", tree({org_key: ("blob", blob(ORG_RECEIPT))})),
        "repository-ledger": ("tree", tree({SOURCE_ORG: ("tree", tree({".github": ("tree", repo_tree)}))})),
    })
    tip = _git(bare, "commit-tree", top, "-m", "fixture ledger copy")
    _git(bare, "update-ref", pi.LEDGER_REF, tip)
    return tip


class PublicLedgerRoute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tip = build_copy(self.root)
        self.checked = {"path_id": PID, "communication_id": CID, "source_repository": SOURCE_REPOSITORY,
                        "source_organization_receipt_sha256": ORG_RECEIPT["receipt_sha256"],
                        "source_repository_receipt_sha256": REPO_RECEIPT["receipt_sha256"]}
        self.no_tvc = self.root / "no-tvc-receipts"

    def test_carried_row_is_for_this_destination(self):
        self.assertEqual(INBOUND["destination_repository"], DESTINATION_ORG + "/.github")
        self.assertEqual(ROW["source_ledger_tip_observed"], ROW["source_ledger_tip_observed"].lower())

    def test_public_readback_reads_the_carried_sealed_pair(self):
        rb = pi.public_readback(PID, CID, SOURCE_REPOSITORY, self.root)
        self.assertEqual((rb["schema"], rb["repository"], rb["ledger_tip"], rb["read_route"]),
                         (pi.READBACK_SCHEMA, SOURCE_REPOSITORY, self.tip, "ANONYMOUS_PUBLIC_LEDGER_READ"))
        self.assertEqual(rb["organization_receipt"], ORG_RECEIPT)
        self.assertEqual(rb["repository_receipt"], REPO_RECEIPT)
        self.assertTrue(pi._included(rb, rb["organization_receipt"]))
        checked = pi.check_source_pair(rb["organization_receipt"], rb["repository_receipt"], PID, CID, DESTINATION_ORG)
        self.assertEqual(checked["disposition"], "ALLOW", checked)
        self.assertEqual(pi.public_readback(PID, CID, SOURCE_REPOSITORY, self.root), rb)   # deterministic

    def test_source_inclusion_allows_without_any_credential(self):
        got = pi.source_inclusion(self.checked, self.no_tvc, self.root)
        self.assertEqual((got["disposition"], got["state"], got["source_ledger_tip"], got["tvc_read_receipt"]),
                         ("ALLOW", pi.PUBLIC_STATE, self.tip, None))

    def test_public_readback_carries_the_sealed_head_epoch(self):
        # The source head receipt's $.hb_reference.epoch is the head epoch (TVC route parity); never a clock.
        epoch = ORG_RECEIPT["hb_reference"]["epoch"]
        self.assertEqual(pi.public_readback(PID, CID, SOURCE_REPOSITORY, self.root)["ledger_head_epoch"], epoch)
        got = pi.source_inclusion(self.checked, self.no_tvc, self.root)
        self.assertEqual((got["disposition"], got["source_ledger_head_epoch"]), ("ALLOW", epoch))

    def test_head_epoch_is_none_unless_a_supplied_integer(self):
        for hb in (None, {}, {"epoch": "469411750"}, {"epoch": True}, {"epoch": 1}, {"epoch": 4.6e8}):
            with self.subTest(hb=hb):
                self.assertIsNone(pi.head_epoch({"hb_reference": hb}))
        self.assertIsNone(pi.head_epoch(None))
        self.assertEqual(pi.head_epoch({"hb_reference": {"epoch": 469411750}}), 469411750)

    def test_contradicted_copy_is_deny_with_six_fields(self):
        got = pi.source_inclusion({**self.checked, "source_repository_receipt_sha256": "sha256:" + "0" * 64},
                                  self.no_tvc, self.root)
        self.assertEqual((got["disposition"], got["failure_code"]), ("DENY", pi.SOURCE_LINK_UNVERIFIED))
        self.assertTrue(all(got[f] for f in SIX))

    def test_no_anonymous_copy_falls_back_to_the_tvc_route_fail_closed(self):
        for public in (self.root / "absent", self.root / "none"):
            with self.subTest(public=public):
                got = pi.source_inclusion(self.checked, self.no_tvc, public)
                self.assertEqual((got["disposition"], got["failure_code"]), ("FAIL_CLOSED", pi.CREDENTIAL_NOT_ISSUED))
                self.assertTrue(all(got[f] for f in SIX))

    def test_unsafe_organization_names_are_not_resolved(self):
        for other in ("../x/.github", "/.github", ".hidden/.github", ""):
            self.assertIsNone(pi.public_ledger_dir(other, self.root))

    def test_end_to_end_is_terminal_at_e0(self):
        # No destination ingress receipt yet: terminal FAIL_CLOSED with six fields, never waiting.
        src = pi.public_readback(PID, CID, SOURCE_REPOSITORY, self.root)
        dst = {"schema": pi.READBACK_SCHEMA, "repository": DESTINATION_ORG + "/.github", "ledger_tip": None,
               "head_receipt_sha256": None, "chain": [], "organization_receipt": None, "repository_receipt": None}
        got = pi.verify_end_to_end(PID, CID, src, dst)
        self.assertEqual((got["disposition"], got["failure_code"], got["half"]),
                         ("FAIL_CLOSED", pi.NOT_LEDGERED, "end_to_end"))
        self.assertTrue(all(got[f] for f in SIX))


DEST_PID = "SV-011->StegVerse-org:intr-destination"
DEST_CID = "intr-path-v1:SV-011->StegVerse-org"
DEST_REPOSITORY = "StegVerse-org/.github"
DECLARED = "INTR_MESH_PATH_INGRESS:" + DEST_PID + "@" + DEST_CID
ANNOTATION = ROOT / ".stegverse" / "intr-path-transfer" / "destination-duplicate-annotations.v1.json"
ANNOTATION_DOC = ROOT / "docs" / "INTR_DESTINATION_DUPLICATE_RECEIPTS.md"


def _sha(byte: str) -> str:
    return "sha256:" + byte * 32


def destination_copy(root: Path, newer_suffix: str, older_inclusion) -> tuple[str, str, str]:
    """A bare StegVerse-org.git whose destination chain is oldest, then a later receipt. Returns tip and the two org shas."""
    oldest_org, newer_org = _sha("11"), _sha("22")
    oldest_repo, newer_repo = _sha("33"), _sha("44")
    bare = root / "StegVerse-org.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    def blob(doc) -> str:
        return _git(bare, "hash-object", "-w", "--stdin", data=(json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())

    def tree(entries: dict[str, tuple[str, str]]) -> str:
        lines = "".join(("100644 blob " if kind == "blob" else "040000 tree ") + sha + "\t" + name + "\n"
                        for name, (kind, sha) in sorted(entries.items()))
        return _git(bare, "mktree", data=lines.encode())

    def org(digest, previous, repo_digest):
        return {"receipt_sha256": digest, "previous_receipt_sha256": previous, "repo_receipt_sha256": repo_digest,
                "hb_reference": {"epoch": 446655631},
                "boundary_evidence": {"operation": "ORGANIZATION_INTR_DESTINATION_INGRESS", "disposition": "ALLOW",
                                      "path_id": DEST_PID, "communication_id": DEST_CID}}

    def repo(digest, transition_id, inclusion):
        return {"receipt_sha256": digest, "transition_id": transition_id,
                "evidence": {"source_inclusion": inclusion, "disposition": "ALLOW"}}

    oldest_key = oldest_org.split(":", 1)[1] + ".json"
    newer_key = newer_org.split(":", 1)[1] + ".json"
    oldest_repo_key = oldest_repo.split(":", 1)[1] + ".json"
    newer_repo_key = newer_repo.split(":", 1)[1] + ".json"
    receipts = tree({oldest_key: ("blob", blob(org(oldest_org, None, oldest_repo))),
                     newer_key: ("blob", blob(org(newer_org, oldest_org, newer_repo)))})
    repo_receipts = tree({
        oldest_repo_key: ("blob", blob(repo(oldest_repo, DECLARED, older_inclusion))),
        newer_repo_key: ("blob", blob(repo(newer_repo, DECLARED + newer_suffix,
                                           {"state": pi.PUBLIC_STATE, "source_ledger_tip": "ab" * 20,
                                            "tvc_read_receipt": None}))),
    })
    top = tree({
        "HEAD.json": ("blob", blob({"receipt_sha256": newer_org})),
        "receipts": ("tree", receipts),
        "repository-ledger": ("tree", tree({
            "StegVerse-org": ("tree", tree({".github": ("tree", tree({"receipts": ("tree", repo_receipts)}))})),
        })),
    })
    tip = _git(bare, "commit-tree", top, "-m", "fixture destination ledger copy")
    _git(bare, "update-ref", pi.LEDGER_REF, tip)
    return tip, oldest_org, newer_org


class PublicDestinationDuplicate(unittest.TestCase):
    """The anonymous destination read grants the oldest receipt. A later one is a duplicate and grants nothing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_later_destination_receipt_on_the_public_copy_is_a_duplicate_and_the_oldest_is_read(self):
        tip, oldest, newer = destination_copy(
            self.root, pi.SOURCE_INCLUSION_PACKET_SUFFIX, "UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL")
        got = pi.public_readback(DEST_PID, DEST_CID, DEST_REPOSITORY, self.root)
        self.assertEqual(got["ledger_tip"], tip)
        self.assertEqual(got["organization_receipt"]["receipt_sha256"], oldest)
        self.assertEqual(got["head_receipt_sha256"], newer)
        self.assertEqual(got["ledger_head_epoch"], 446655631)
        self.assertNotIn("refused", got)
        (finding,) = got["duplicate_receipts"]
        self.assertEqual((finding["finding"], finding["grants"], finding["organization_receipt_sha256"],
                          finding["declared"]),
                         (pi.DUPLICATE_OF_CROSSING, "NOTHING", newer, True))

    def test_an_undeclared_later_destination_receipt_on_the_public_copy_is_refused(self):
        _, oldest, newer = destination_copy(self.root, "#forged-claim", "UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL")
        got = pi.public_readback(DEST_PID, DEST_CID, DEST_REPOSITORY, self.root)
        self.assertEqual(got["organization_receipt"]["receipt_sha256"], oldest)
        refused = got["refused"]
        self.assertEqual(refused["failure_code"], "INTR_PATH_DESTINATION_SUCCESSOR_UNDECLARED")
        self.assertTrue(all(refused.get(field) for field in SIX))
        self.assertEqual(refused["duplicate_receipts"][0]["organization_receipt_sha256"], newer)
        self.assertEqual(refused["duplicate_receipts"][0]["grants"], "NOTHING")


class CommittedDuplicateAnnotation(unittest.TestCase):
    def test_the_committed_duplicate_annotation_names_each_later_receipt_non_authoritative(self):
        doc = json.loads(ANNOTATION.read_text(encoding="utf-8"))
        prose = ANNOTATION_DOC.read_text(encoding="utf-8")
        self.assertEqual(doc["schema"], "stegverse.intr-destination-duplicate-annotation/v1")
        self.assertEqual(doc["authority_effect"], "NONE")
        self.assertEqual(doc["ledger_ref"], pi.LEDGER_REF)
        self.assertEqual(len(doc["ledger_tip"]), 40)
        self.assertEqual(doc["inbound_crossings_with_two_allow_destination_receipts"], 10)
        self.assertEqual(doc["of_which_in_original_8_org_mesh"], 5)
        self.assertEqual(len(doc["crossings"]), 10)
        self.assertIn(doc["ledger_tip"], prose)
        self.assertIn(doc["excluded_not_a_path_crossing"]["organization_receipt_sha256"], prose)
        mesh = 0
        seen = set()
        for crossing in doc["crossings"]:
            self.assertNotIn(crossing["path_id"], seen)
            seen.add(crossing["path_id"])
            first, later = crossing["authoritative"], crossing["duplicate"]
            self.assertEqual((first["authoritative"], first["generation"]), (True, 1))
            self.assertEqual((later["authoritative"], later["generation"], later["finding"], later["grants"]),
                             (False, 2, pi.DUPLICATE_OF_CROSSING, "NOTHING"))
            self.assertTrue(later["is_org_250_source_inclusion_successor"])
            self.assertTrue(later["transition_id"].endswith(pi.SOURCE_INCLUSION_PACKET_SUFFIX))
            self.assertFalse(first["transition_id"].endswith(pi.SOURCE_INCLUSION_PACKET_SUFFIX))
            self.assertEqual(first["source_inclusion"], "UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL")
            self.assertEqual(later["source_inclusion_state"], pi.PUBLIC_STATE)
            self.assertEqual(len(later["source_ledger_tip"]), 40)
            self.assertEqual((later["writer_run"], later["writer_pull_request"]), (40152359683, 250))
            self.assertNotEqual(first["organization_receipt_sha256"], later["organization_receipt_sha256"])
            for digest in (first["organization_receipt_sha256"], first["repository_receipt_sha256"],
                           later["organization_receipt_sha256"], later["repository_receipt_sha256"]):
                self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
                self.assertIn(digest, prose)
            if crossing["in_original_8_org_mesh"]:
                mesh += 1
                self.assertIn(crossing["path_id"].split(":")[0].split("->")[0], doc["original_8_org_mesh"])
        self.assertEqual(mesh, 5)


if __name__ == "__main__":
    unittest.main()
