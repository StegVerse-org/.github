"""InTr mesh path ingress: the destination half (carried source receipts -> this organization's ingress receipts).

Every source receipt here is SYNTHETIC: built and sealed in this test for a path
into this organization, never read from any ledger. Destination receipts are written
to temporary copies of the pinned ledger tip. Nothing here is ledgered or
authentic. Real destination receipts appear only once an inbound row carrying
real source receipts lands on main and .github/workflows/intr-path-ingress.yml
consumes it.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:   # pytest: hold the organization to org-contract.json's own organization_ledger declaration
    import pytest
    pytestmark = pytest.mark.repository_ledger_locus
except (ImportError, AttributeError):
    pass

ROOT = Path(__file__).resolve().parents[1]
LEDGER_TIP = json.loads((ROOT / "tests/fixtures/intr-path-ingress/pin.json").read_text())["ledger_tip"]
NAMESPACE = json.loads((ROOT / ".stegverse/transition-ledger/contract.json").read_text())[
    "repository_ledger_location"]["namespace"]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pi = load("intr_path_ingress_under_test", "resident-runtime/intr_path_ingress.py")
sys.path.insert(0, str(ROOT / "tests"))
from intr_path_temp_ledger import TempLedger  # noqa: E402
DESTINATION = pi.organization()
SOURCE = "SV-011" if DESTINATION != "SV-011" else "StegVerse-org"
OTHER = "SV-LLM" if DESTINATION != "SV-LLM" else "StegGhost"
PID = SOURCE + "->" + DESTINATION + ":intr-destination"
CID = "intr-path-v1:" + SOURCE + "->" + DESTINATION


def seal(body):
    body = {k: v for k, v in body.items() if k != "receipt_sha256"}
    return {**body, "receipt_sha256": pi.sha(body)}


def synthetic_source(path_id=PID, cid=CID, destination=DESTINATION, **evidence_overrides):
    message = {"message_class": "ecosystem.communication", "communication_id": cid,
               "body": {"schema": pi.ingress.PAYLOAD_SCHEMA, "path_id": path_id, "transfer_commit": "a" * 40}}
    core = {"schema": pi.SOURCE_EVIDENCE_SCHEMA, "repository": SOURCE + "/.github", "path_id": path_id,
            "source_organization": SOURCE, "destination_organization": destination, "capability": "intr-destination",
            "destination_address": pi.address(destination), "message": message, "message_sha256": pi.sha(message),
            "transfer_commit": "a" * 40, "merge_transfer_organization_receipt_sha256": "sha256:" + "b" * 64}
    core.update(evidence_overrides)
    evidence = {**core, "payload_sha256": pi.sha(core), "disposition": "ALLOW", "communication_id": cid}
    repo = seal({"schema": "stegverse.repo-transition-receipt/v1", "repository": SOURCE + "/.github",
                 "evidence": evidence, "synthetic": "NOT_LEDGERED_NOT_AUTHENTIC"})
    org = seal({"schema": "stegverse.organization-transition-receipt/v1", "source_repository": SOURCE + "/.github",
                "repo_receipt_sha256": repo["receipt_sha256"], "previous_receipt_sha256": None,
                "boundary_evidence": {"operation": pi.SOURCE_OPERATION, "path_id": path_id, "communication_id": cid},
                "synthetic": "NOT_LEDGERED_NOT_AUTHENTIC"})
    return org, repo


class Ledger(TempLedger):
    def __init__(self, inbound=None):
        super().__init__(ROOT, LEDGER_TIP, NAMESPACE, git=pi.ledger.kind == "MERGE_TRANSFER_GITSTORE")
        self.scratch = tempfile.TemporaryDirectory()
        self.inbound = Path(self.scratch.name) / "inbound.json"

    def write_inbound(self, rows):
        self.inbound.write_text(json.dumps({"schema": pi.INBOUND_SCHEMA, "destination_repository": DESTINATION + "/.github",
                                            "transfers": rows}))
        return self.inbound

    def close(self):
        super().close()
        self.scratch.cleanup()


FIXED = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@invalid", "GIT_AUTHOR_DATE": "@0 +0000",
         "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@invalid", "GIT_COMMITTER_DATE": "@0 +0000"}


class PublicCopy:
    """A temporary stand-in for the anonymous copy of the source's public ledger (what
    tools/tasks/intr_public_ledgers.sh fetches before consume): a bare <SOURCE>.git whose ledger ref holds
    HEAD.json -> the given synthetic source receipts. Fixed dates; no network, clock or credential."""

    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.saved = os.environ.get(pi.PUBLIC_LEDGERS_ENV)
        os.environ[pi.PUBLIC_LEDGERS_ENV] = str(self.root)

    def _git(self, bare, *args, data=None):
        return subprocess.run(["git", "--git-dir=" + str(bare), *args], input=data, capture_output=True, check=True,
                              env={**os.environ, **FIXED}).stdout.decode().strip()

    def publish(self, org, repo):
        bare = self.root / (SOURCE + ".git")
        if not bare.is_dir():
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        blob = lambda doc: self._git(bare, "hash-object", "-w", "--stdin",
                                     data=(json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
        tree = lambda entries: self._git(bare, "mktree", data="".join(
            ("100644 blob " if kind == "blob" else "040000 tree ") + sha + "\t" + name + "\n"
            for name, (kind, sha) in sorted(entries.items())).encode())
        key = lambda receipt: receipt["receipt_sha256"].split(":", 1)[1] + ".json"
        repo_tree = tree({"receipts": ("tree", tree({key(repo): ("blob", blob(repo))}))})
        top = tree({"HEAD.json": ("blob", blob({"receipt_sha256": org["receipt_sha256"]})),
                    "receipts": ("tree", tree({key(org): ("blob", blob(org))})),
                    "repository-ledger": ("tree", tree({SOURCE: ("tree", tree({".github": ("tree", repo_tree)}))}))})
        tip = self._git(bare, "commit-tree", top, "-m", "fixture public ledger copy")
        self._git(bare, "update-ref", pi.LEDGER_REF, tip)
        return tip

    def withdraw(self):
        """The anonymous read failed: no copy of the source ledger."""
        subprocess.run(["rm", "-rf", str(self.root / (SOURCE + ".git"))], check=True)

    def close(self):
        if self.saved is None:
            os.environ.pop(pi.PUBLIC_LEDGERS_ENV, None)
        else:
            os.environ[pi.PUBLIC_LEDGERS_ENV] = self.saved
        self.dir.cleanup()


def row(org, repo, pid=PID, cid=CID):
    return {"path_id": pid, "communication_id": cid,
            "carried": {"source_organization_receipt": org, "source_repository_receipt": repo}}


def source_readback(org, repo):
    return {"schema": pi.READBACK_SCHEMA, "repository": SOURCE + "/.github", "ledger_tip": "synthetic",
            "head_receipt_sha256": org["receipt_sha256"], "chain": [org], "organization_receipt": org,
            "repository_receipt": repo}


class Consume(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        self.public = PublicCopy()

    def tearDown(self):
        self.public.close()
        self.ledger.close()

    def six(self, result):
        for field in pi.SIX_FIELDS:
            self.assertTrue(result.get(field), field)

    def test_no_inbound_file_is_no_transition(self):
        self.assertEqual(pi.consume(Path(self.ledger.scratch.name) / "absent.json"), [])

    def test_carried_receipts_enter_ingress_and_link_by_seal(self):
        org, repo = synthetic_source()
        tip = self.public.publish(org, repo)
        before = self.ledger.files()
        (result,) = pi.consume(self.ledger.write_inbound([row(org, repo)]))
        self.assertEqual(result["disposition"], "ALLOW", result)
        self.assertEqual((result["source_inclusion"]["disposition"], result["source_inclusion"]["state"],
                          result["source_inclusion"]["source_ledger_tip"]), ("ALLOW", pi.PUBLIC_STATE, tip))
        after = self.ledger.files()
        for name, data in before.items():
            if not name.endswith("HEAD.json"):
                self.assertEqual(after[name], data, name)
        d_org, d_rep, _ = pi.find_destination(PID, CID)
        self.assertEqual(pi.ledger.boundary(d_org)["operation"], "ORGANIZATION_INTR_DESTINATION_INGRESS")
        self.assertEqual(pi.ledger.boundary(d_org)["source_organization_receipt_sha256"], org["receipt_sha256"])
        self.assertEqual(d_rep["evidence"]["source_repository_receipt_sha256"], repo["receipt_sha256"])
        self.assertEqual(d_rep["evidence"]["source_inclusion"],
                         {"state": pi.PUBLIC_STATE, "source_ledger_tip": tip, "tvc_read_receipt": None})
        self.assertIsNone(pi.recorded_inclusion(d_rep))
        (verified,) = pi.verify_inbound(self.ledger.inbound)
        self.assertEqual(verified["disposition"], "ALLOW", verified)
        (replay,) = pi.consume(self.ledger.inbound)
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.ledger.files(), after)

    def test_end_to_end_is_allow_only_with_both_ledgers_read_back(self):
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        pi.consume(self.ledger.write_inbound([row(org, repo)]))
        destination = pi.readback(PID, CID, pi.OPERATION, "temp")
        whole = pi.verify_end_to_end(PID, CID, source_readback(org, repo), destination)
        self.assertEqual((whole["disposition"], whole["path"]), ("ALLOW", "VERIFIED"), whole)
        blind = pi.verify_end_to_end(PID, CID, None, destination)
        self.assertEqual((blind["disposition"], blind["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED"))
        self.assertIn("StegVerse-Labs/TVC", blind["retry_entrypoint"])
        self.assertIn(SOURCE + "/.github", blind["retry_entrypoint"])
        self.six(blind)
        other_org, other_repo = synthetic_source(cid="intr-path-v1:other")
        mismatch = pi.verify_end_to_end(PID, CID, source_readback(other_org, other_repo), destination)
        self.assertEqual(mismatch["disposition"], "DENY", mismatch)
        self.six(mismatch)

    def test_destination_receipt_linking_another_source_is_denied(self):
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        pi.consume(self.ledger.write_inbound([row(org, repo)]))
        d_org, d_rep, _ = pi.find_destination(PID, CID)
        forged = seal({**repo, "evidence": {**repo["evidence"], "tree": "x"}})
        link = {"path_id": PID, "communication_id": CID, "source_organization_receipt_sha256": org["receipt_sha256"],
                "source_repository_receipt_sha256": forged["receipt_sha256"]}
        result = pi.verify_destination_pair(d_org, d_rep, link)
        self.assertEqual((result["disposition"], result["failure_code"]),
                         ("DENY", "INTR_PATH_DESTINATION_RECEIPT_LINK_UNVERIFIED"))
        self.six(result)

    def test_refusals_write_nothing(self):
        org, repo = synthetic_source()
        before = self.ledger.files()
        cases = [
            (row(None, None), "FAIL_CLOSED", "INTR_PATH_SOURCE_RECEIPT_NOT_CARRIED"),
            (row(*synthetic_source(destination=OTHER)), "DENY", "INTR_PATH_CARRIED_RECEIPT_CONTRADICTED"),
            (row(*synthetic_source(destination_address=pi.address(OTHER))), "DENY",
             "INTR_PATH_CARRIED_RECEIPT_CONTRADICTED"),
            (row(org, synthetic_source(cid="intr-path-v1:other")[1]), "DENY", "INTR_PATH_CARRIED_RECEIPT_CONTRADICTED"),
        ]
        tampered = copy.deepcopy(org)
        tampered["boundary_evidence"]["path_id"] = "x"
        cases.append((row(tampered, repo), "FAIL_CLOSED", "INTR_PATH_SOURCE_RECEIPT_NOT_CARRIED"))
        for r, disposition, code in cases:
            with self.subTest(code=code):
                (result,) = pi.consume(self.ledger.write_inbound([r]))
                self.assertEqual((result["disposition"], result["failure_code"]), (disposition, code), result)
                self.six(result)
        self.assertEqual(self.ledger.files(), before)
        (unledgered,) = pi.verify_inbound(self.ledger.write_inbound([row(org, repo)]))
        self.assertEqual((unledgered["disposition"], unledgered["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_DESTINATION_RECEIPT_NOT_LEDGERED"))
        self.six(unledgered)

    def test_a_failed_anonymous_source_read_writes_nothing_and_is_fail_closed(self):
        org, repo = synthetic_source()
        before = self.ledger.files()
        (result,) = pi.consume(self.ledger.write_inbound([row(org, repo)]))
        self.assertEqual((result["disposition"], result["failure_code"], result["appended"]),
                         ("FAIL_CLOSED", "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED", False), result)
        self.six(result)
        self.assertEqual(self.ledger.files(), before)
        self.assertEqual(pi.find_destination(PID, CID)[0], None)

    def _legacy_first_receipt(self, org, repo):
        """What the writer recorded before it read the source ledger: the crossing's one receipt, inclusion unobserved."""
        checked = pi.check_source_pair(org, repo, PID, CID, DESTINATION)
        epoch, failed = pi.ledger.head_epoch()
        self.assertIsNone(failed)
        legacy = pi.ingress_evidence(checked, None)
        self.assertEqual(legacy["source_inclusion"], "UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL")
        appended, _ = pi.ledger.append(
            pi.TRANSITION_CLASS, PID + "@" + CID, legacy, epoch, operation=pi.OPERATION,
            profile_id=pi.ingress.PROFILE_ID,
            boundary_extra={"path_id": PID, "source_repository": checked["source_repository"],
                            "source_organization_receipt_sha256": org["receipt_sha256"],
                            "source_repository_receipt_sha256": repo["receipt_sha256"]})
        return appended["organization_receipt"]["receipt_sha256"], legacy

    def test_a_crossing_that_has_a_receipt_never_gets_a_second_one(self):
        # Rigel (2026-10-29): "This shouldn't be possible without being a literal duplicate." One receipt per
        # crossing: consume answers from the ledger and appends nothing, even when the receipt recorded the source
        # inclusion as unobserved and the source ledger is readable now.
        org, repo = synthetic_source()
        first, _ = self._legacy_first_receipt(org, repo)
        inbound = self.ledger.write_inbound([row(org, repo)])
        self.public.publish(org, repo)
        before = self.ledger.files()
        (refused,) = pi.consume(inbound)
        self.assertEqual((refused["disposition"], refused["failure_code"], refused["appended"]),
                         ("FAIL_CLOSED", "INTR_PATH_DESTINATION_CROSSING_ALREADY_RECORDED", False), refused)
        self.assertEqual(refused["organization_receipt_sha256"], first)
        self.six(refused)
        self.assertEqual(self.ledger.files(), before)
        # and again: still nothing written
        (again,) = pi.consume(inbound)
        self.assertEqual(again["failure_code"], "INTR_PATH_DESTINATION_CROSSING_ALREADY_RECORDED")
        self.assertEqual(self.ledger.files(), before)

    def test_an_observed_receipt_is_answered_from_the_ledger_and_nothing_is_appended(self):
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        inbound = self.ledger.write_inbound([row(org, repo)])
        (first,) = pi.consume(inbound)
        self.assertEqual((first["disposition"], first["replayed"]), ("ALLOW", False), first)
        after = self.ledger.files()
        (again,) = pi.consume(inbound)
        self.assertTrue(again["replayed"], again)
        self.assertEqual(self.ledger.files(), after)
        self.public.withdraw()
        (still,) = pi.consume(inbound)   # an observed receipt needs no further read
        self.assertTrue(still["replayed"], still)
        self.assertEqual(self.ledger.files(), after)

    def test_the_writer_guard_refuses_a_second_receipt_that_appears_after_the_row_was_read(self):
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        inbound = self.ledger.write_inbound([row(org, repo)])
        real, calls = pi.find_destinations, []

        def raced(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return real(*args, **kwargs)   # the row is read: no receipt yet
            self._legacy_first_receipt(org, repo)   # another writer appended the crossing's receipt meanwhile
            return real(*args, **kwargs)
        pi.find_destinations = raced
        try:
            (refused,) = pi.consume(inbound)
        finally:
            pi.find_destinations = real
        self.assertEqual((refused["disposition"], refused["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_DESTINATION_CROSSING_ALREADY_RECORDED"), refused)
        self.six(refused)
        pairs, _ = pi.find_destinations(PID, CID)
        self.assertEqual(len(pairs), 1)   # only the other writer's receipt: the crossing still has exactly one

    def test_a_historical_second_receipt_is_a_duplicate_of_the_same_crossing_and_grants_nothing(self):
        # Ledger history is append-only: StegVerse-org's ledger holds, for ten crossings, a first receipt that
        # recorded the inclusion as unobserved and a later #source-inclusion receipt. The later one is a duplicate
        # of the same crossing. It is identified, it grants nothing, and it is not the crossing's receipt.
        org, repo = synthetic_source()
        first, legacy = self._legacy_first_receipt(org, repo)
        self.public.publish(org, repo)
        checked = pi.check_source_pair(org, repo, PID, CID, DESTINATION)
        epoch, failed = pi.ledger.head_epoch()
        observed = pi.ingress_evidence(checked, pi.source_inclusion(checked))
        appended, _ = pi.ledger.append(
            pi.TRANSITION_CLASS, PID + "@" + CID + pi.SOURCE_INCLUSION_PACKET_SUFFIX, observed, epoch,
            operation=pi.OPERATION, profile_id=pi.ingress.PROFILE_ID,
            boundary_extra={"path_id": PID, "source_repository": checked["source_repository"],
                            "source_organization_receipt_sha256": org["receipt_sha256"],
                            "source_repository_receipt_sha256": repo["receipt_sha256"]})
        duplicate = appended["organization_receipt"]["receipt_sha256"]
        inbound = self.ledger.write_inbound([row(org, repo)])
        d_org, _, _ = pi.find_destination(PID, CID)
        self.assertEqual(d_org["receipt_sha256"], first)   # the crossing's receipt is the first
        (verified,) = pi.verify_inbound(inbound)
        self.assertEqual(verified["disposition"], "ALLOW", verified)
        self.assertEqual(verified["organization_receipt_sha256"], first)
        self.assertEqual(verified["source_inclusion_recorded"][:len("source_inclusion is recorded as")],
                         "source_inclusion is recorded as")
        self.assertEqual(verified["source_inclusion_observed_at_verification"]["state"], pi.PUBLIC_STATE)
        (finding,) = verified["duplicate_receipts"]
        self.assertEqual((finding["finding"], finding["grants"], finding["organization_receipt_sha256"]),
                         ("INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING", "NOTHING", duplicate))
        self.assertTrue(finding["declared"])
        # the duplicate grants nothing: with the source ledger unreadable, the crossing's own receipt decides
        self.public.withdraw()
        (denied,) = pi.verify_inbound(inbound)
        self.assertEqual((denied["disposition"], denied["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_SOURCE_INCLUSION_UNOBSERVED"), denied)
        self.assertEqual(denied["organization_receipt_sha256"], first)
        self.six(denied)
        # readback names the crossing's receipt and carries the duplicate
        destination = pi.readback(PID, CID, pi.OPERATION, "temp")
        self.assertEqual(destination["organization_receipt"]["receipt_sha256"], first)
        self.assertEqual(destination["duplicate_receipts"][0]["organization_receipt_sha256"], duplicate)
        whole = pi.verify_end_to_end(PID, CID, source_readback(org, repo), destination)
        self.assertEqual(whole["disposition"], "ALLOW", whole)
        self.assertEqual(whole["destination_organization_receipt_sha256"], first)

    def test_an_unauthorized_successor_is_refused(self):
        # StegVerse-org/.github#162: a successor on the same destination pair that is not the declared
        # #source-inclusion successor, or that records no source-inclusion read, must not become the path's receipt.
        # Any later receipt for the crossing is a duplicate of it: refused here, never granting anything.
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        inbound = self.ledger.write_inbound([row(org, repo)])
        (authorized,) = pi.consume(inbound)
        self.assertEqual(authorized["disposition"], "ALLOW", authorized)
        (verified,) = pi.verify_inbound(inbound)
        self.assertEqual(verified["disposition"], "ALLOW", verified)
        checked = pi.check_source_pair(org, repo, PID, CID, DESTINATION)
        epoch, failed = pi.ledger.head_epoch()
        self.assertIsNone(failed)
        unobserved = pi.ingress_evidence(checked, None)
        core = {k: v for k, v in unobserved.items()
                if k not in ("source_inclusion", "payload_sha256", "disposition", "communication_id")}
        absent = {**core, "payload_sha256": pi.sha(core), "disposition": "ALLOW", "communication_id": CID}
        forged = pi.ingress_evidence(checked, {"disposition": "ALLOW", "state": pi.PUBLIC_STATE,
                                               "source_ledger_tip": "c" * 40, "tvc_read_receipt": None})
        first = authorized["organization_receipt_sha256"]
        cases = (("#unauthorized-unobserved", unobserved, "INTR_PATH_DESTINATION_SUCCESSOR_UNDECLARED"),
                 ("#unauthorized-absent", absent, "INTR_PATH_DESTINATION_SUCCESSOR_UNDECLARED"),
                 # claims an observed inclusion it never read: the suffix is not the declared one
                 ("#forged-claim", forged, "INTR_PATH_DESTINATION_SUCCESSOR_UNDECLARED"),
                 # the declared suffix over a receipt that already recorded an observed inclusion is a duplicate of
                 # the same crossing and is refused
                 (pi.SOURCE_INCLUSION_PACKET_SUFFIX, unobserved, "INTR_PATH_DESTINATION_SUCCESSOR_PREDECESSOR_OBSERVED"))
        for suffix, evidence, code in cases:
            with self.subTest(suffix=suffix):
                appended, _ = pi.ledger.append(
                    pi.TRANSITION_CLASS, PID + "@" + CID + suffix, evidence, epoch, operation=pi.OPERATION,
                    profile_id=pi.ingress.PROFILE_ID,
                    boundary_extra={"path_id": PID, "source_repository": checked["source_repository"],
                                    "source_organization_receipt_sha256": org["receipt_sha256"],
                                    "source_repository_receipt_sha256": repo["receipt_sha256"]})
                d_org, _, _ = pi.find_destination(PID, CID)
                self.assertEqual(d_org["receipt_sha256"], first)   # the crossing's receipt stays the first
                (refused,) = pi.verify_inbound(inbound)
                self.assertEqual((refused["disposition"], refused["failure_code"]), ("FAIL_CLOSED", code), refused)
                self.assertEqual(refused["organization_receipt_sha256"], appended["organization_receipt"]["receipt_sha256"])
                self.six(refused)

    def _successor(self, org, repo, suffix, evidence):
        checked = pi.check_source_pair(org, repo, PID, CID, DESTINATION)
        epoch, failed = pi.ledger.head_epoch()
        self.assertIsNone(failed)
        appended, _ = pi.ledger.append(
            pi.TRANSITION_CLASS, PID + "@" + CID + suffix, evidence(checked), epoch, operation=pi.OPERATION,
            profile_id=pi.ingress.PROFILE_ID,
            boundary_extra={"path_id": PID, "source_repository": checked["source_repository"],
                            "source_organization_receipt_sha256": org["receipt_sha256"],
                            "source_repository_receipt_sha256": repo["receipt_sha256"]})
        return appended["organization_receipt"]["receipt_sha256"]

    def test_readback_carries_an_undeclared_successor_refusal_to_end_to_end(self):
        # #258 review finding 2: the local half of the end-to-end check holds this ledger's own destination
        # receipts to the same two transition ids as verify_inbound.
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        pi.consume(self.ledger.write_inbound([row(org, repo)]))
        forged = self._successor(org, repo, "#forged-claim", lambda checked: pi.ingress_evidence(checked, {
            "disposition": "ALLOW", "state": pi.PUBLIC_STATE, "source_ledger_tip": "c" * 40, "tvc_read_receipt": None}))
        destination = pi.readback(PID, CID, pi.OPERATION, "temp")
        self.assertNotEqual(destination["organization_receipt"]["receipt_sha256"], forged)   # the first is the crossing's
        whole = pi.verify_end_to_end(PID, CID, source_readback(org, repo), destination)
        self.assertEqual((whole["disposition"], whole["failure_code"], whole["path"]),
                         ("FAIL_CLOSED", "INTR_PATH_DESTINATION_SUCCESSOR_UNDECLARED", "UNVERIFIED"), whole)
        self.assertEqual(whole["organization_receipt_sha256"], forged)
        self.assertEqual(whole["duplicate_receipts"][0]["organization_receipt_sha256"], forged)
        self.six(whole)

    def test_a_source_inclusion_successor_over_an_observed_predecessor_is_refused(self):
        # #258 review finding 3 (c71f23c): the #source-inclusion successor exists only to record an inclusion its
        # predecessor recorded as unobserved. Over an already-observed predecessor it is refused.
        org, repo = synthetic_source()
        self.public.publish(org, repo)
        inbound = self.ledger.write_inbound([row(org, repo)])
        (observed,) = pi.consume(inbound)
        self.assertEqual((observed["disposition"], observed["source_inclusion"]["state"]), ("ALLOW", pi.PUBLIC_STATE))
        successor = self._successor(org, repo, pi.SOURCE_INCLUSION_PACKET_SUFFIX, lambda checked: pi.ingress_evidence(
            checked, {"disposition": "ALLOW", "state": pi.PUBLIC_STATE, "source_ledger_tip": "c" * 40,
                      "tvc_read_receipt": None}))
        (refused,) = pi.verify_inbound(inbound)
        self.assertEqual((refused["disposition"], refused["failure_code"]),
                         ("FAIL_CLOSED", "INTR_PATH_DESTINATION_SUCCESSOR_PREDECESSOR_OBSERVED"), refused)
        self.assertEqual(refused["organization_receipt_sha256"], successor)
        self.six(refused)


if __name__ == "__main__":
    unittest.main()
