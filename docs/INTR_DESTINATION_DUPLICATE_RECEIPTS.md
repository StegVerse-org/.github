# Inbound destination receipts that are duplicates

Authoring-Session: lane-b-91117956. Owning goal: StegVerse-org/.github#162.

Anonymous read of `refs/stegverse/organization-ledger` on `StegVerse-org/.github` at tip `b98d08ac8b120a82c2346a68ed5547ac61125bdb`. The fetch used an empty credential helper and no auth header. This document annotates later receipts. It is not a ledger record, and the append-only ledger is not rewritten.

Each InTr crossing has exactly one destination receipt. The oldest ALLOW receipt is authoritative. A later ALLOW receipt is `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING` and grants nothing. The writer refuses a new second receipt with the six fields (`INTR_PATH_DESTINATION_CROSSING_ALREADY_RECORDED`).

Ten inbound crossings into StegVerse-org have two ALLOW `ORGANIZATION_INTR_DESTINATION_INGRESS` receipts. Five of them are in the original 8-organization mesh (StegVerse-org, StegVerse-Labs, SV-011, SV-LLM, GCAT-BCAT-Engine, StegGhost, StegVerse-002, Admissible-Existence). SV-011 and StegVerse-002 have one receipt each. The one pathless ALLOW receipt `sha256:51a48225fb0229c54f1e6f2a703c215c9f86b467c0b9b0815a401bb6835c5a64` is the 2026-10-17 self-close (`intr-selfclose-StegVerse-org-20261017`), not a path crossing.

Every generation-2 receipt is the `#source-inclusion` successor written by organization-ledger-writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683) on the push of org#250 (`3e9485e7`, 2026-10-25 01:54Z). Generation 1 recorded `source_inclusion` as `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`. Generation 2 recorded `VERIFIED_BY_ANONYMOUS_PUBLIC_LEDGER_READ`. That observed-inclusion fact lives only on the duplicate and grants nothing. The machine-readable copy is `.stegverse/intr-path-transfer/destination-duplicate-annotations.v1.json`.

## AaCT-E->StegVerse-org:intr-destination

Outside the original 8-org mesh. Communication `intr-path-v1:AaCT-E->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:a655f4f99fc79ae447e13fed0f36e29484e5fef03589e96b65b86d5b7faa450e`, repository `sha256:a0a47c1c7b0c0fc769f92e8999a78a4137b78b9dd8b71fe97e7bfe2fdadcb4f3`. Ledger commit `aeee58a9e379f7ae6f917ddc2ee9db5bfe7705d5` at 2026-10-24T21:17:44+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:e4617a549f8c3296a0a5a14c9912c88199708a0b55ffb616d257ce7f5c7c5a34`, repository `sha256:33278f7ec4be6513aad7c144d4a9433d88b183049016f8f2c3ca04cd5f44e31b`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `f4e57239ed65ced32e739db74e92a59615239567` at 2026-10-25T01:54:16+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `c90c967d0b954ae91d3b9916f820f2d75805271c`. This is the org#250 successor.

## Admissible-Existence->StegVerse-org:intr-destination

In the original 8-org mesh. Communication `intr-path-v1:Admissible-Existence->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:1a56ecaa611f15ca8b62d3b732daaf01fed76f6402a56c6ac2d0e1faacaf6fba`, repository `sha256:1e1dec9e1e14376f29e8bfd06d850e92c9fe655c8559d3492871cbb4ebfc0081`. Ledger commit `eae68d3aaa625d573f0343670c9e65cc5d656c5d` at 2026-10-24T21:17:46+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:b0f19fecbc4f617c190b467e0de913f07a721f23beb5ee971cecdd2c264d086f`, repository `sha256:d161220615354c2872a65a5c1c88ffb17d55d72433880ca1365c6363bc2fc1af`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `538836c0f918c59edf523cf21e66952ba7bd92a6` at 2026-10-25T01:54:17+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `a2ef2f0e2f13d7f682b7b6f80b099e95260c0f7b`. This is the org#250 successor.

## AdmittedCode->StegVerse-org:intr-destination

Outside the original 8-org mesh. Communication `intr-path-v1:AdmittedCode->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:fdb2ec79ef0983820b8ce88b25459992b895c1a207d8300be89ef5ef8f1e41ca`, repository `sha256:b1c5385cb65c88969cecb93795556b399af97acb1979ffa139b9506ad35b52c8`. Ledger commit `93ed4ce00d0f2dfc6e32279778a16afdd505723c` at 2026-10-24T21:17:48+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:49c7d9a7509bc0d3622dce83f32cddbd113367a95084e3c183c6c54f24939b7f`, repository `sha256:939759c2c23972a4499a0b5ca0a45a2d6a45ea4d7de3dd9dde4af6b92723f38e`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `7c44a366aac5d8efc47ba35a0130d09b6f6a0d75` at 2026-10-25T01:54:19+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `bb0d2e576ca3eed416070f6e7b93ce9615205f62`. This is the org#250 successor.

## Data-Continuation->StegVerse-org:intr-destination

Outside the original 8-org mesh. Communication `intr-path-v1:Data-Continuation->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:dc065479a20b0ca261649578a67bdc41eef58587a631d5a0767a243ed4f61ec1`, repository `sha256:6bc38a664bbf6b2b5bc392bcb17ef7703f764c55719e9ad4a5076b2eb8f0f03c`. Ledger commit `ef7819672b89ea185f234ebe8fb334d39ae1c24e` at 2026-10-24T21:17:49+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:d098613de525acbbb172d45b548993b8ccfb6eee7f8f7d77f8b97735fd12c627`, repository `sha256:369cfe59b180ed5ef39064efc79d1074167e4b07296c9da93957cc014c265886`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `a5f96721ea761ceae700df6eea98e3151e4f19c4` at 2026-10-25T01:54:21+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `9c13d00d5d33548da5e876f61e4e16f8cc266831`. This is the org#250 successor.

## ECAT-ICAT-Formal->StegVerse-org:intr-destination

Outside the original 8-org mesh. Communication `intr-path-v1:ECAT-ICAT-Formal->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:2d869bc4a48950521f23f1b5881be30ebfad63f9cfa4943ac591ec7f66b0be4b`, repository `sha256:0af0543c3199b6abfb9bfcfd7d0dad02ee10f9d3727eb9aa465f87c5e620baf6`. Ledger commit `1c2fe043a6ae499e59cd3993d10942096555672a` at 2026-10-24T21:17:51+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:98db1521a8a2ad80c6d264e25fa7dd6b1e9fec3e5b8e8cd317e24d4152c31e56`, repository `sha256:bb74555a1c9e16c9a43524269ffc8bc0bfa076d91b53fc3f158287e7914ee4e4`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `af17e232cf02f446adbd37677a9c1281b9ca6b43` at 2026-10-25T01:54:23+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `22f7f391d41bb55a49bd08e612e6bf267c87a806`. This is the org#250 successor.

## GCAT-BCAT-Engine->StegVerse-org:intr-destination

In the original 8-org mesh. Communication `intr-path-v1:GCAT-BCAT-Engine->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:17601726e12251bd98a90dd24bfcced2d5cdaa21d07b690b9e51e620166d0fee`, repository `sha256:92496594493c1005b11c0d9f0d015bda6a4b0eb6108741f918ebcec875be32e7`. Ledger commit `bf8dd7a7dc8f654c3e662fa6a18bb566ebc83adf` at 2026-10-24T22:04:51+00:00. Writer run [40136959077](https://github.com/StegVerse-org/.github/actions/runs/40136959077) on the push of #244 (`8dc5882d6993170e8592dfb6b4fba48c103c796a`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:28581a91d143b76580cba7a9a1f34218b3b450ba47a3fe94cfe7cb85e43cbdd3`, repository `sha256:24073bf0e20e180425a0536290410a65cf3e899bc211c28e43e5b11054ee7650`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `db8dedf73a30aea03d986e3f367fd5abe5da2565` at 2026-10-25T01:54:24+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `827ef13b35612d5bfd1d761f823f10b8f4a7f9d3`. This is the org#250 successor.

## SV-LLM->StegVerse-org:intr-destination

In the original 8-org mesh. Communication `intr-path-v1:SV-LLM->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:b57521ad4adab9300ac1cb97f05168d2a39db3a79a474d614d1124571b447159`, repository `sha256:b833cb5f413a43cad1c6c601d8f28252e04dff14abf9462802a7479dbd91e381`. Ledger commit `e675fd46584295917db7197343c9a4ac258bc6df` at 2026-10-24T19:25:44+00:00. Writer run [40125200566](https://github.com/StegVerse-org/.github/actions/runs/40125200566) on the push of #240 (`60e2d7c9212bbe0c57427ba55d92a2b44fc807ad`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:1eadb5bcd7e1c4845f56dd8fcb136b2d72b7bc1fd2cca785b84ec32c88fcdd0f`, repository `sha256:6a5a0aa3ceca78eaa2c34effba17253980d94085e0e0b21292c12d2b2271c33a`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `13027f08f76decc1654bbe0b980d2c689c4a2532` at 2026-10-25T01:54:26+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `35fa61f7a49eef56621d7f872fd87a64640fff51`. This is the org#250 successor.

## StegGhost->StegVerse-org:intr-destination

In the original 8-org mesh. Communication `intr-path-v1:StegGhost->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:f5c1468932fbb2df6c0cb58a844adbcd3565c99a2564d1d3b41c1f8d33d53d6f`, repository `sha256:91b65d6282c7db4cb1a7c9646f93ec14b024ec2ea2904efe63b7596ea56781e1`. Ledger commit `f482db03d747b601c6335879f88d5259b429d39a` at 2026-10-24T19:25:45+00:00. Writer run [40125200566](https://github.com/StegVerse-org/.github/actions/runs/40125200566) on the push of #240 (`60e2d7c9212bbe0c57427ba55d92a2b44fc807ad`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:18e4b18ddf3a0114b561ebbdd8727b5e3341acb557f50c23e91477e41fa6206c`, repository `sha256:9cade490250802913fa4b5d28dd31f7acbf7979a14566732a80d5659a8e044f4`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `1bedce5e2ed0938d88f8ede907456b21c9ac69e6` at 2026-10-25T01:54:28+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `174479421d120697105930c5309041ba5e756947`. This is the org#250 successor.

## StegVerse-Labs->StegVerse-org:intr-destination

In the original 8-org mesh. Communication `intr-path-v1:StegVerse-Labs->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:e4e9d2e3729f43d652f8b27f6dd0b1e05dc9fe319706289e54c68a1715fcb1cf`, repository `sha256:7ef7635988b1d6b527304783d74f85f550844a7fd984a76e3c80b95cb102b633`. Ledger commit `f839ac4dc935a3767f820492f7d5cca46e5abf29` at 2026-10-24T18:55:53+00:00. Writer run [40122918308](https://github.com/StegVerse-org/.github/actions/runs/40122918308) on the push of #224 (`575c520dd0cf6974814c62c43cc0688a976333f8`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:b122500ada62a06d4549f157e587a5c2652293d801128db03f643dddf6d43a79`, repository `sha256:f43924e56631b8a4afc701162b4e74ecea6265ed5355f2f306134d0a263c48d4`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `9bd210add9621fd16ab37e16e4636be2e43f7c65` at 2026-10-25T01:54:30+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `89067f0d8da1e6b1aef33ab79074743cce1b743f`. This is the org#250 successor.

## Triad-Test->StegVerse-org:intr-destination

Outside the original 8-org mesh. Communication `intr-path-v1:Triad-Test->StegVerse-org`. Both receipts carry hb epoch 446655631.

- Authoritative (generation 1): organization `sha256:5c1e684bdf97fe22ecea7d0817f4ac2eca369ce3a0b7deffecc87cef78d8057a`, repository `sha256:dbd02a2fb8d787939aa8c23d8f979fbbe65dcbeccec62c5b699319e4af72bfb8`. Ledger commit `5d0df718635df8e85ddd148db356714332cfb69f` at 2026-10-24T21:17:54+00:00. Writer run [40133531528](https://github.com/StegVerse-org/.github/actions/runs/40133531528) on the push of #243 (`e5eb83678484ba7a43a8f0a2fff2a7ca5b48ce1c`). Inclusion `UNOBSERVED_WITHOUT_A_CROSS_ORG_READ_CREDENTIAL`.
- Duplicate (generation 2, grants nothing): organization `sha256:c6741a049ea5663adaf7c98bbf77406144ad2f5476751615a335c9f95dc3bc00`, repository `sha256:a19253e2184c31e2a78ba238d3f0ebfbf3aa6903997e9f5a1e7efffc6b30221a`. Finding `INTR_PATH_DESTINATION_DUPLICATE_OF_THE_SAME_CROSSING`. Ledger commit `a195bc908ed051545704fe521a77e85cd0f37109` at 2026-10-25T01:54:32+00:00. Same writer run [40152359683](https://github.com/StegVerse-org/.github/actions/runs/40152359683), org#250. Transition id ends in `#source-inclusion`. Source ledger tip `3ae26b03927a66141260ac084ac9bc3086049c07`. This is the org#250 successor.
