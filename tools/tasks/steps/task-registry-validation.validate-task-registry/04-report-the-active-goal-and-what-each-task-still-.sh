python - <<'PY'
import json
registry = json.load(open("orchestration/task-registry.json"))
goal = registry["active_goal"]
print("active_goal:", goal)
assert goal in {t["task_id"] for t in registry["tasks"]}
for task in registry["tasks"]:
    print(f"  {task['status']:12} {task['task_id']:38} record #{task['issue']}")
open_tasks = [t for t in registry["tasks"]
              if t["status"] not in {"complete", "merged", "archived"}]
assert all(t.get("required_evidence") for t in open_tasks), \
    "an open task names no evidence that would close it"
print(f"ORGANIZATION_TASK_REGISTRY_RESOLVED=PASS open={len(open_tasks)}")
PY
