# ORG_BOUNDARY_MIRROR_HANDOFF.md

Status: ACTIVE
Updated: 2026-10-18
Organization: StegVerse-org
Repository: StegVerse-org/.github

## Canonical rule
Every StegVerse-org resident runtime activation surface is owned by and kept in `StegVerse-org/.github`.

All communication crossing the StegVerse-org organizational boundary is generated through this repository's Interlock/InTr ingress and egress mechanisms.

Application repositories expose capabilities and endpoint profiles. They do not independently become the organization resident-runtime activation authority.

## HB / InTr
HB or HB-derived carriers provide synchronization/carrier capability only. Carrier presence grants no admission, execution, credential, routing, transition, receiving, publication, custody, or release authority.

InTr governs the packets carried across the organization boundary. Applicable transition elements determine authority effects.

## Responsibilities
Ingress: observe carrier -> validate InTr envelope -> bind provenance and transition context -> resolve destination/profile -> dispatch -> receipt.
Egress: validate result/evidence -> resolve destination org -> generate governed InTr envelope -> emit receipt -> preserve reconstruction linkage.

## Runtime home
- `resident-runtime/`
- `org-boundary/runtime/`
- `org-runtime/`: the activation and boundary declarations (`activation.json`, `interlock-intr.json`) and their generator and validator, `runtime_boundary.py` (`activation.json` `activation_request_generator`)
- `org-kernel/`: the kernel, referenced by `resident-runtime/activation-manifest.json` and vendored here from `canonical_source: StegVerse-Labs/.github/org-kernel`; this copy is the one this organization runs
- organization-specific existing resident/runtime machinery referenced by the activation manifest

GitHub Actions may validate or convey evidence but are not sovereign runtime authority.

## Migration rule
Legacy organization-runtime activation surfaces outside `StegVerse-org/.github` are endpoint/provider implementations or migration sources, not competing organizational activation points.
