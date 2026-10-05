"""A console must say what reality it is watching, or it misleads by omission.

Two things were never established, and a console is where both become visible
to whoever is reading.

The first is what "live" can mean for a state transition in an ecosystem whose
ordering is `OSCILLATOR_HEARTBEAT_EPOCH_ONLY` and which has no host to push
from. It cannot mean a tail of a stream. It means visible at the epoch the
reader sampled, and the console says so rather than letting a scrolling
surface imply otherwise.

The second is the difference between fetching the SDK and running it locally,
and running it against a production ecosystem over a network. That difference
produces completely different evidence, and nothing made a run declare which
one it was in. The mesh store already knew -- the provenance vocabulary is
`node_store`'s -- so these cases hold the console to reading it rather than
declaring a second one, and to stating on every run that no networked mode
exists.

Source validation only. No authority effect is claimed.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TC = _module("transition_console", "resident-runtime/transition_console.py")
NS = _module("node_store_for_console", "org-kernel/node_store.py")
REGISTRY = json.loads((ROOT / "orchestration/task-registry.json").read_text(encoding="utf-8"))


def receipt(index, previous, successor, *, transition_class="SYNTHETIC", epoch=32):
    return {"receipt_sha256": "sha256:" + str(index) * 8,
            "previous_receipt_sha256": previous,
            "successor_state_sha256": successor,
            "transition_class": transition_class,
            "authority_effect": "NONE",
            "hb_reference": {"epoch": epoch, "derived_from_clock": False}}


def chain():
    return [receipt(1, None, "s1", transition_class="ORGANIZATION_EGRESS_EMITTED"),
            receipt(2, "sha256:" + "1" * 8, "s2",
                    transition_class="OBSERVATION_WINDOW_OPENED", epoch=5000)]


class RunModeTests(unittest.TestCase):
    """The mode is supplied by the materializer, never inferred from a host."""

    def test_a_supplied_root_is_materializer_supplied(self):
        resolved = TC.run_mode(root=Path("/tmp/a-mesh"))
        self.assertEqual(resolved["run_mode"], TC.MATERIALIZER_SUPPLIED)
        self.assertEqual(resolved["mesh_provenance"], NS.SUPPLIED)
        self.assertTrue(resolved["mesh_portable"])

    def test_host_environment_is_not_a_mesh_binding(self):
        with self.assertRaisesRegex(ValueError, "host_environment_mesh_binding_forbidden"):
            TC.run_mode(root=Path("/tmp/a-mesh"),
                        env={"STEGVERSE_ORG_FEDERATION_ROOT": "/srv/shared/mesh"})

    def test_missing_materializer_root_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "mesh_location_required_from_materializer"):
            TC.run_mode(root=None)

    def test_only_supplied_provenance_is_portable(self):
        self.assertEqual(set(NS.PORTABLE_PROVENANCE), {NS.SUPPLIED})


class MeshAxisTests(unittest.TestCase):
    """The console reports only the supplied mesh axis, not route authority."""

    def mode(self):
        return TC.run_mode(root=Path("/tmp/m"))

    def test_mode_declares_which_axis_it_reports(self):
        resolved = self.mode()
        self.assertEqual(resolved["axis"], "MESH_MEDIUM")
        self.assertTrue(resolved["route_axis_is_not_resolved_here"])

    def test_mode_makes_no_claim_about_the_ecosystem_at_large(self):
        resolved = self.mode()
        self.assertNotIn("reaches_a_production_ecosystem_over_a_network", resolved)
        self.assertNotIn("network_transport_implemented", resolved)

    def test_the_mesh_claim_is_scoped_to_this_organizations_medium(self):
        resolved = self.mode()
        self.assertTrue(resolved["mesh_medium_is_a_shared_filesystem_or_nothing"])
        self.assertTrue(resolved["two_parties_sharing_no_filesystem_cannot_share_this_mesh"])
        self.assertIn("this organization's mesh store kind", resolved["why"])

    def test_the_route_axis_is_cited_to_the_surface_that_owns_it(self):
        resolved = self.mode()
        self.assertEqual(resolved["route_axis_field"], "routing_surface")
        self.assertIn("route_resolution.py", resolved["route_axis_owner"])
        self.assertIn("StegVerse-SDK", resolved["route_axis_owner"])

    def test_the_reason_is_the_store_kind_rather_than_an_opinion(self):
        resolved = self.mode()
        self.assertEqual(resolved["store_kind"], "POSIX_FILESYSTEM")
        self.assertIn(resolved["store_kind"], resolved["why"])

    def test_the_only_materialized_state_store_here_is_filesystem_backed(self):
        self.assertEqual(NS.PosixStateStore.kind, "POSIX_FILESYSTEM")


class LiveMeansTests(unittest.TestCase):

    def test_live_is_not_a_pushed_stream(self):
        live = TC.live_means()
        self.assertFalse(live["is_a_pushed_stream"])
        self.assertEqual(live["becomes_visible"], "AT_THE_EPOCH_THE_READER_SAMPLES")

    def test_ordering_is_the_oscillators_and_the_wall_clock_is_refused(self):
        live = TC.live_means()
        self.assertEqual(live["ordering"], "OSCILLATOR_HEARTBEAT_EPOCH_ONLY")
        self.assertFalse(live["wall_clock_ordering_permitted"])

    def test_a_gap_between_samples_is_not_an_absence(self):
        self.assertTrue(TC.live_means()["a_gap_between_samples_is_not_an_absence_of_transitions"])


class RenderingTests(unittest.TestCase):

    def test_transitions_carry_the_class_and_the_epoch_they_ran_under(self):
        rows = TC.transitions(chain())
        self.assertEqual([r["transition_class"] for r in rows],
                         ["ORGANIZATION_EGRESS_EMITTED", "OBSERVATION_WINDOW_OPENED"])
        self.assertEqual([r["hb_epoch"] for r in rows], [32, 5000])
        for row in rows:
            with self.subTest(row=row["transition_class"]):
                self.assertFalse(row["hb_derived_from_clock"])

    def test_a_receipt_declaring_no_class_is_marked_undeclared(self):
        bare = [{"receipt_sha256": "sha256:" + "9" * 8, "previous_receipt_sha256": None,
                 "successor_state_sha256": "s", "hb_reference": {"epoch": 32}}]
        self.assertEqual(TC.transitions(bare)[0]["transition_class"], "UNDECLARED")

    def test_one_line_per_transition_in_chain_order(self):
        rendered = TC.view(chain(), root=Path("/tmp/m"))
        self.assertEqual(len(rendered["lines"]), 2)
        self.assertIn("ORGANIZATION_EGRESS_EMITTED", rendered["lines"][0])
        self.assertIn("HB 32", rendered["lines"][0])

    def test_the_view_carries_both_the_run_and_what_live_means(self):
        rendered = TC.view(chain(), root=Path("/tmp/m"))
        self.assertEqual(rendered["run"]["run_mode"], TC.MATERIALIZER_SUPPLIED)
        self.assertFalse(rendered["live"]["is_a_pushed_stream"])
        self.assertEqual(rendered["transition_count"], 2)

    def test_the_console_grants_nothing_and_changes_nothing(self):
        rendered = TC.view(chain(), root=Path("/tmp/m"))
        self.assertEqual(rendered["authority_effect"], "NONE_CONSOLE_ONLY")
        self.assertTrue(rendered["ledger_unchanged_by_this_view"])
        self.assertEqual(rendered["run"]["authority_effect"], "NONE_CONSOLE_ONLY")

    def test_an_empty_chain_renders_nothing_rather_than_a_claim(self):
        rendered = TC.view([], root=Path("/tmp/m"))
        self.assertEqual(rendered["lines"], [])
        self.assertEqual(rendered["transition_count"], 0)


if __name__ == "__main__":
    unittest.main()
