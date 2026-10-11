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
# As received and recorded: -001/-002 declared "known"; -003 was received under
# the pre-migration SDK with its source_output_id left as -002.
RECORDED_HISTORY = {"SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-001": "known",
                    "SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-002": "known",
                    "SDK-MR-A-ORGANIZATION-LEDGER-RECEIPT-003": "bounded"}
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
        recorded = {request["request_id"]: processor["signal"]["uncertainty_state"]
                    for _, request, processor in governance_requests() if request["request_id"] in RECORDED_HISTORY}
        self.assertEqual(recorded, RECORDED_HISTORY)

    def test_every_unrecorded_request_names_itself_consistently(self):
        # -003 carried its predecessor's source_output_id, so its derived request
        # id names -002; the manifest's identities must all name the request.
        for name, request, _ in governance_requests():
            if request["request_id"] in RECORDED_HISTORY:
                continue
            build = request["build_manifest"]
            with self.subTest(request=name):
                self.assertEqual(name, request["request_id"] + ".json")
                self.assertEqual(build.get("source_output_id"), request["request_id"])
                self.assertEqual((build.get("data") or {}).get("request_id"), request["request_id"])


if __name__ == "__main__":
    unittest.main()
