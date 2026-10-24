#!/usr/bin/env python3
"""Lane B (lane-b-91117956, StegVerse-org/.github#162) clock-free, network-free evaluation of anonymous readbacks.
Inputs are only the git objects read_org.sh fetched anonymously. Writes one JSON file; touches no ledger ref.
SKAP invariant: the SKAP Vault inside KV is the only PII and credential store for every user, the ecosystem's own
included; this read needs and holds none (no credential, token or TVC receipt)."""
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

ORG, C, ANON, OUTF = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
REF = "refs/stegverse/organization-ledger"
GOAL = "StegVerse-org/.github#162"
SIX = ("failure_code", "failed_predicate", "required_evidence_or_repair", "retry_entrypoint",
       "owning_existing_goal", "next_attempt")
SKAP = ("SKAP invariant: the SKAP Vault inside KV is the only PII and credential store for every user, the "
        "ecosystem's own included; these anonymous reads need and hold no credential, token or TVC receipt.")
ORGS16 = ("StegVerse-org StegVerse-Labs StegGhost GCAT-BCAT-Engine AaCT-E AdmittedCode ECAT-ICAT-Formal master-records "
          "Triad-Test formalism-tests Data-Continuation Admissible-Existence StegVerse-002 "
          "Infrastructure-Continuity-Ventures SV-011 SV-LLM").split()
RETRY = "/workspace/laneB/reads/read_org.sh <org> (re-run after the org's .github is public / the receipt lands)"


def canon(v): return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def sha(v): return "sha256:" + hashlib.sha256(canon(v)).hexdigest()
def stored_bytes(v): return json.dumps(v, indent=2, sort_keys=True).encode() + b"\n"   # resident-runtime/ledger_store.py
def sealed(r): return isinstance(r, dict) and isinstance(r.get("receipt_sha256"), str) and \
    sha({k: v for k, v in r.items() if k != "receipt_sha256"}) == r["receipt_sha256"]
def six(disposition, code, pred, repair, nxt, entry=RETRY, goal=GOAL, **kw):
    return {"disposition": disposition, "failure_code": code, "failed_predicate": pred,
            "required_evidence_or_repair": repair, "retry_entrypoint": entry, "owning_existing_goal": goal,
            "next_attempt": nxt, **kw}


def lsr(o):
    f = C / "lsr" / f"{o}.txt"
    refs = {}
    if f.exists():
        for line in f.read_text().splitlines():
            if "\t" in line:
                s, r = line.split("\t"); refs[r] = s
    return {"public": "refs/heads/main" in refs, "main": refs.get("refs/heads/main"), "ledger_tip": refs.get(REF)}


def snap(o):
    v = lsr(o); p = C / "main" / f"{o}@{v['main']}" if v["main"] else None
    return p if p and p.is_dir() else None


def jload(p):
    try: return json.loads(Path(p).read_bytes())
    except Exception: return None


def fsha(p):
    return "sha256:" + hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None


class Ledger:
    """One org's ledger ref from the anonymous mirror: all blobs read in one cat-file pass."""
    def __init__(self, o):
        self.org, self.gd = o, str(ANON / f"{o}.git")
        self.tip = self._git("rev-parse", "-q", "--verify", REF).strip() or None
        self.files, self.raw, self.added = {}, {}, {}
        if not self.tip: return
        names = self._git("ls-tree", "-r", "--name-only", REF).split("\n")
        names = [n for n in names if n.endswith(".json")]
        inp = "".join(f"{REF}:{n}\n" for n in names).encode()
        out = subprocess.run(["git", "--git-dir", self.gd, "cat-file", "--batch"], input=inp, capture_output=True).stdout
        i = 0
        for n in names:
            hdr_end = out.index(b"\n", i); size = int(out[i:hdr_end].split()[2])
            data = out[hdr_end + 1: hdr_end + 1 + size]; i = hdr_end + 1 + size + 1
            self.raw[n] = data
            try: self.files[n] = json.loads(data)
            except Exception: self.files[n] = None
        cur = None
        for line in self._git("log", "--format=@%H", "--name-only", "--diff-filter=A", REF, "--").split("\n"):
            if line.startswith("@"): cur = line[1:]
            elif line: self.added[line] = cur   # log is newest-first; oldest add wins below
        self.commits = int(self._git("rev-list", "--count", REF).strip() or 0)

    def _git(self, *a):
        return subprocess.run(["git", "--git-dir", self.gd, *a], capture_output=True, text=True).stdout

    def org_receipt(self, d): return self.files.get(f"receipts/{d.split(':')[-1]}.json") if isinstance(d, str) else None
    def repo_receipt(self, d):
        return self.files.get(f"repository-ledger/{self.org}/.github/receipts/{d.split(':')[-1]}.json") if isinstance(d, str) else None

    def chain(self):
        head = self.files.get("HEAD.json") or {}
        d, seen, out, problems = head.get("receipt_sha256"), set(), [], []
        while isinstance(d, str) and d not in seen:
            seen.add(d); r = self.org_receipt(d)
            if r is None: problems.append(f"{d}: predecessor not in tree"); break
            if not sealed(r) or r["receipt_sha256"] != d: problems.append(f"{d}: seal mismatch")
            out.append(r); d = r.get("previous_receipt_sha256")
        return out, problems

    def readback(self, path_id, cid, op):
        """Same object as resident-runtime/intr_path_ingress.py readback, built from the anonymous git objects."""
        chain, _ = self.chain()
        b = lambda r: r.get("boundary_evidence") or {}
        found = next((r for r in chain if b(r).get("operation") == op and b(r).get("path_id") == path_id
                      and b(r).get("communication_id") == cid), None)
        head = chain[0]["receipt_sha256"] if chain else None
        return {"schema": "stegverse.intr-path-ledger-readback/v1", "repository": f"{self.org}/.github",
                "ledger_tip": self.tip, "head_receipt_sha256": head,
                "chain": chain[:chain.index(found) + 1] if found else [], "organization_receipt": found,
                "repository_receipt": self.repo_receipt(found.get("repo_receipt_sha256")) if found else None}


def tool():
    root = snap("StegVerse-org")
    if not root: return None, None
    spec = importlib.util.spec_from_file_location("intr_path_ingress_main", root / "resident-runtime/intr_path_ingress.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m
    cwd = os.getcwd(); os.chdir(root)
    try: spec.loader.exec_module(m)
    finally: os.chdir(cwd)
    return m, root


def main():
    vis = {o: lsr(o) for o in ORGS16 + ([ORG] if ORG not in ORGS16 else [])}
    me = vis[ORG]
    res = {"schema": "lane-b.intr-org-anonymous-read/v1", "authoring_session": "lane-b-91117956",
           "owning_existing_goal": GOAL, "organization": ORG, "repository": f"{ORG}/.github",
           "access": "anonymous https (git ls-remote / git fetch, no credential helper, no token, no TVC receipt)",
           "skap_invariant": SKAP, "ledger_writes": "none", "dispatch": "none",
           "visibility_16": {o: {"anonymous_readable": v["public"], "main": v["main"], "ledger_tip": v["ledger_tip"]}
                             for o, v in vis.items()}}
    if not me["public"]:
        res["result"] = six("FAIL_CLOSED", "ORG_DOT_GITHUB_NOT_ANONYMOUSLY_READABLE", "ORG_DOT_GITHUB_IS_PUBLIC",
                            f"{ORG}/.github made public (owner visibility flip in progress)",
                            "re-run read_org.sh right after the flip")
        OUTF.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n"); print(json.dumps(res["result"])); return
    m, oroot = tool(); lroot = snap("StegVerse-Labs"); groot = snap(ORG)
    # ---- 1. destination read ----
    fed = jload(lroot / "org-boundary/registry/federation.json") if lroot else None
    fed_row = next((r for r in (fed or {}).get("organizations", []) if r.get("organization") == ORG), None)
    proto = jload(oroot / "data/intr-protocol/v1/protocol.json") if oroot else None
    man = jload(oroot / "tests/fixtures/intr-protocol/destinations/manifest.json") if oroot else None
    mrow = next((d for d in (man or {}).get("destinations", []) if d.get("organization") == ORG), None)
    mesh_orgs = [d["organization"] for d in (man or {}).get("destinations", [])]
    try: dest_id = m.address(ORG) if m else None
    except Exception as e: dest_id = f"<address() failed: {e}>"
    live = {}
    for rel in ("org-runtime/interlock-intr.json", "org-boundary/registry/services.json",
                ".stegverse/intr-path-transfer/inbound.json", ".stegverse/intr-path-transfer/transfers.json",
                "resident-runtime/intr_path_ingress.py", "resident-runtime/intr_path_transfer.py",
                "resident-runtime/intr_destination_ingress.py", ".github/workflows/intr-path-ingress.yml",
                ".github/workflows/intr-path-transfer.yml", "data/intr-protocol/v1/protocol.json"):
        live[rel] = fsha(groot / rel) if groot else None
    adverts = sorted(str(p.relative_to(groot)) for p in groot.rglob("*") if p.is_file()
                     and not str(p.relative_to(groot)).startswith(("source-bundles/", ".git/"))   # vendored bundle copies, not adverts
                     and any(k in p.name.lower() for k in ("intr", "destination", "carrier", "interlock"))) if groot else []
    svc = jload(groot / "org-boundary/registry/services.json") if groot else None
    svc_rows = [s for s in (svc.get("services", []) if isinstance(svc, dict) else []) if isinstance(s, dict)
                and "intr-destination" in json.dumps(s)] if svc else []
    inbound = jload(groot / ".stegverse/intr-path-transfer/inbound.json") if groot else None
    transfers = jload(groot / ".stegverse/intr-path-transfer/transfers.json") if groot else None
    snapshot_fresh = None
    if mrow and groot:
        snapshot_fresh = {k: {"manifest": mrow[k]["sha256"], "live": fsha(groot / mrow[k]["source_path"]),
                              "match": mrow[k]["sha256"] == fsha(groot / mrow[k]["source_path"])}
                          for k in ("interlock", "services") if isinstance(mrow.get(k), dict)}
    res["destination"] = {
        "destination_id": dest_id, "destination_repository": f"{ORG}/.github", "read_at_commit": me["main"],
        "federation_row": fed_row, "federation_read_at": {"repository": "StegVerse-Labs/.github",
            "path": "org-boundary/registry/federation.json", "commit": vis["StegVerse-Labs"]["main"]},
        "protocol_entry": {"repository": "StegVerse-org/.github", "commit": vis["StegVerse-org"]["main"],
            "protocol": (proto or {}).get("protocol"), "declared_paths_rule": ((proto or {}).get("mesh_path_transfer") or {}).get("declared_paths"),
            "in_conformance_manifest": mrow is not None, "manifest_row": mrow, "manifest_snapshot_vs_live": snapshot_fresh},
        "org_dot_github_files_sha256": live, "intr_named_files": adverts, "intr_destination_service_rows": svc_rows,
        "inbound_rows": (inbound or {}).get("inbound", (inbound or {}).get("rows")) if isinstance(inbound, dict) else inbound,
        "transfer_rows": (transfers or {}).get("transfers") if isinstance(transfers, dict) else None}
    # ---- 2. ledger receipt read ----
    L = Ledger(ORG)
    lg = {"ref": REF, "anonymous_tip": me["ledger_tip"], "mirror_tip": L.tip}
    if not L.tip:
        lg["result"] = six("FAIL_CLOSED", "ORGANIZATION_LEDGER_REF_ABSENT", "ORGANIZATION_LEDGER_HEAD_PRESENT",
                           f"{ORG}/.github has no {REF}: its organization-ledger workflow has not appended a first receipt",
                           "re-run read_org.sh after the org's first ledger append is observed",
                           entry=f"{ORG}/.github organization ledger main-merge transfer workflow (push to main; no dispatch)")
        lg["receipts"] = []
    else:
        chain, problems = L.chain()
        on = {r["receipt_sha256"] for r in chain}
        tree = {n: r for n, r in L.files.items() if n.startswith("receipts/")}
        lg.update({"ledger_commits": L.commits, "org_chain_length": len(chain), "org_receipt_files": len(tree),
                   "off_chain_receipt_files": sorted(n for n, r in tree.items() if not (isinstance(r, dict) and r.get("receipt_sha256") in on)),
                   "chain_problems": problems,
                   "all_chain_receipts_sealed": all(sealed(r) for r in chain),
                   "all_chain_receipts_canonical_bytes": all(L.raw[f"receipts/{r['receipt_sha256'][7:]}.json"] == stored_bytes(r) for r in chain),
                   "chain_terminates_at_genesis": bool(chain) and chain[-1].get("previous_receipt_sha256") is None and not problems})
        recs = []
        for r in chain:
            b = r.get("boundary_evidence") or {}; op = b.get("operation", "")
            if op == "INTR_MESH_PATH_TRANSFER": kind = "transfer"
            elif op == "ORGANIZATION_INTR_DESTINATION_INGRESS": kind = "ingress" if b.get("path_id") else "destination"
            else: continue
            n = f"receipts/{r['receipt_sha256'][7:]}.json"; rr = L.repo_receipt(r.get("repo_receipt_sha256"))
            pid = b.get("path_id"); ends = pid.split(":")[0].split("->") if pid else []
            peer = b.get("destination_organization") if kind == "transfer" else (b.get("source_organization") or (ends[0] if ends else None))
            recs.append({"kind": kind, "operation": op, "path_id": pid, "communication_id": b.get("communication_id"),
                         "peer_org": peer if kind != "destination" else None, "receipt_sha256": r["receipt_sha256"], "ledger_commit": L.added.get(n),
                         "transfer_commit": b.get("transfer_commit") or b.get("commit"),
                         "repo_receipt_sha256": r.get("repo_receipt_sha256"),
                         "checks": {"sealed": sealed(r), "canonical_bytes": L.raw.get(n) == stored_bytes(r),
                                    "on_head_chain": True, "repo_receipt_present": rr is not None,
                                    "repo_receipt_sealed": sealed(rr),
                                    "repo_receipt_canonical_bytes": rr is not None and L.raw.get(f"repository-ledger/{ORG}/.github/receipts/{rr['receipt_sha256'][7:]}.json") == stored_bytes(rr)}})
        lg["receipts"] = recs
        lg["receipt_counts"] = {k: sum(1 for x in recs if x["kind"] == k) for k in ("transfer", "ingress", "destination")}
        lg["all_intr_receipts_verify"] = all(all(x["checks"].values()) for x in recs)
    res["ledger"] = lg
    # ---- 3. end-to-end per declared path with this org as an endpoint ----
    paths = []
    if ORG in mesh_orgs and m:
        cache = {ORG: L}
        for peer in [o for o in mesh_orgs if o != ORG]:
            for s, d in ((ORG, peer), (peer, ORG)):
                pid, cid = f"{s}->{d}:intr-destination", f"intr-path-v1:{s}->{d}"
                rbs = {}
                for half, o, op in (("source", s, "INTR_MESH_PATH_TRANSFER"), ("destination", d, "ORGANIZATION_INTR_DESTINATION_INGRESS")):
                    if not vis.get(o, {}).get("public"): rbs[half] = None; continue
                    cache.setdefault(o, Ledger(o)); lo = cache[o]
                    # public org without a ledger ref: an empty readback (anonymous read succeeded, nothing ledgered)
                    rbs[half] = lo.readback(pid, cid, op) if lo.tip else {"schema": "stegverse.intr-path-ledger-readback/v1",
                        "repository": f"{o}/.github", "ledger_tip": None, "head_receipt_sha256": None, "chain": [],
                        "organization_receipt": None, "repository_receipt": None}
                try: r = m.verify_end_to_end(pid, cid, rbs["source"], rbs["destination"])
                except Exception as e:
                    r = six("FAIL_CLOSED", "VERIFIER_RAISED", "VERIFY_END_TO_END_RUNS", repr(e), "fix and re-run")
                row = {"path_id": pid, "source": s, "destination": d,
                       "both_endpoints_anonymously_readable": bool(vis.get(s, {}).get("public") and vis.get(d, {}).get("public")),
                       "source_ledger_tip": cache[s].tip if s in cache else None,
                       "destination_ledger_tip": cache[d].tip if d in cache else None,
                       "disposition": r.get("disposition"), "half": r.get("half")}
                if r.get("disposition") != "ALLOW":
                    row.update({k: r.get(k) for k in SIX})
                    if row["failure_code"] == "INTR_PATH_CROSS_ORG_READ_CREDENTIAL_NOT_ISSUED":
                        row["note"] = ("verifier's class-A code: that endpoint's .github is not yet anonymously readable; "
                                       "under the all-public invariant no credential is issued -- it clears when the repo goes public, re-run read_org.sh")
                else:
                    row.update({k: r.get(k) for k in ("source_organization_receipt_sha256", "destination_organization_receipt_sha256")})
                paths.append(row)
    res["paths"] = paths
    both = [p for p in paths if p["both_endpoints_anonymously_readable"]]
    res["path_counts"] = {"declared_with_org_endpoint": len(paths), "both_endpoints_readable": len(both),
                          "allow": sum(p["disposition"] == "ALLOW" for p in paths),
                          "allow_where_both_readable": sum(p["disposition"] == "ALLOW" for p in both),
                          "by_failure_code": {c: sum(1 for p in paths if p.get("failure_code") == c)
                                              for c in sorted({p.get("failure_code") for p in paths if p.get("failure_code")})},
                          "mesh_orgs_in_manifest": mesh_orgs}
    if ORG not in mesh_orgs:
        res["path_counts"]["note"] = six("FAIL_CLOSED", "ORG_NOT_IN_INTR_DESTINATION_MANIFEST", "DESTINATION_DOCUMENTS_CONFORM",
            f"{ORG} destination documents (org-runtime/interlock-intr.json + org-boundary/registry/services.json) conforming and snapshotted into StegVerse-org/.github tests/fixtures/intr-protocol/destinations/manifest.json",
            "after the snapshot refresh lands, re-run read_org.sh",
            entry="python org-runtime/intr_protocol.py conform --org <ORG> --interlock <interlock-intr.json> --services <services.json>")
    OUTF.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"org": ORG, "main": me["main"], "destination_id": dest_id, "ledger_tip": L.tip,
                      "counts": lg.get("receipt_counts"), "paths": res["path_counts"]}))


main()
