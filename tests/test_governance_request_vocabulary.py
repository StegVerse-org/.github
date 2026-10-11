"""A committed governance transition request uses the deciding organization's request vocabulary.

SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-002 declared signal.uncertainty_state
"known". StegCore's AdmissibilityRequest (StegVerse-Labs/StegCore
src/stegcore/steggate.py) accepts only bounded | material | unknown, so even
with the evaluator present the request could only be refused as not evaluable
(StegVerse-Labs/.github#3099, StegVerse-SDK#465). This organization does not
import StegCore (tests/test_governance_inter_org_route.py), so the declared
values are restated here. Requests already received and recorded on the ledger
are history and are not rewritten.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / ".stegverse/transition-requests"
RECORDED_HISTORY = {"SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-001", "SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-002"}
UNCERTAINTY_STATES = {"bounded", "material", "unknown"}
REQUIRED_SECTIONS = {"candidate", "judgment", "signal", "execution"}


def governance_requests():
    for path in sorted(REQUESTS.glob("*.json")):
        request = json.loads(path.read_text())
        build = request.get("build_manifest") or {}
        if build.get("process") == "governance":
            yield path.name, request, build.get("processor_request") or {}


class GovernanceRequestVocabulary(unittest.TestCase):
    def test_there_is_a_governance_request_to_check(self):
        self.assertTrue(any(name for name, request, _ in governance_requests()
                            if request["request_id"] not in RECORDED_HISTORY))

    def test_every_unrecorded_governance_request_is_evaluable_by_the_deciding_organization(self):
        for name, request, processor in governance_requests():
            if request["request_id"] in RECORDED_HISTORY:
                continue
            with self.subTest(request=name):
                self.assertTrue(REQUIRED_SECTIONS <= set(processor), sorted(processor))
                self.assertIn((processor.get("signal") or {}).get("uncertainty_state"), UNCERTAINTY_STATES)

    def test_the_recorded_requests_stay_as_they_were_received(self):
        known = {request["request_id"]: processor["signal"]["uncertainty_state"]
                 for _, request, processor in governance_requests() if request["request_id"] in RECORDED_HISTORY}
        self.assertEqual(known, {request_id: "known" for request_id in RECORDED_HISTORY})


if __name__ == "__main__":
    unittest.main()
