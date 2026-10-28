python3 - <<'PY'
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["LABS"], "scripts"))
try:
    from test_set_selection import seal_verifies
    sel = json.load(open(os.path.join(os.environ["RESULTS"], "test-set-selection.json")))
    summary = {"receipt_sha256": sel.get("receipt_sha256"), "seal_verifies": seal_verifies(sel),
               "core_selected": any(s["id"] == "core" and s["runnable"] for s in sel.get("selected", [])),
               "mode": sel.get("mode"), "sets_total": sel.get("sets_total"),
               "head_sha": sel.get("head_sha"), "base_sha": sel.get("base_sha"),
               "pr_head_sha": sel.get("pr_head_sha"),
               "selected_count": sel.get("selected_count"),
               "input_unavailable": [{"set": u["set"], "input": u["input"], "owner": u["owning_existing_goal"]}
                                     for u in sel.get("input_unavailable", [])]}
except Exception as exc:  # noqa: BLE001
    summary = {"error": repr(exc)}
print(json.dumps(summary, sort_keys=True))
with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
    fh.write("selection=" + json.dumps(summary, sort_keys=True) + "\n")
with open(os.path.join(os.environ["RESULTS"], "selection-summary.json"), "w") as fh:
    fh.write(json.dumps(summary, sort_keys=True) + "\n")
PY
