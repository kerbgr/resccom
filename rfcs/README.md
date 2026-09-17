# RFCs

Design decisions that change architecture or principles are made in writing here, not in chat or issues.

## Process

1. Copy the structure of [rfc-0001](rfc-0001-architecture.md): Status / Context / Decision / Consequences / Open questions.
2. Number sequentially (`rfc-NNNN-short-title.md`). Open a PR; discussion happens on the PR.
3. Statuses: `Draft` → `Accepted` | `Rejected` | `Superseded by rfc-NNNN`.
4. An accepted RFC is binding until superseded. Agents (see [CLAUDE.md](../CLAUDE.md)) treat accepted RFCs as ground truth.

## Index

| RFC | Title | Status |
|---|---|---|
| [0001](rfc-0001-architecture.md) | Architecture & founding decisions | Accepted |
| 0002 | IMS/VoLTE go/no-go (WBS 4.4) — note: native-112 support is a major pro-IMS argument, see RFC-0004 D4 | Not started |
| [0003](rfc-0003-roaming.md) | Roaming between sovereign islands: home-routed auth, trust ceremony, bounded partition behaviour | Draft |
| [0004](rfc-0004-emergency-interop.md) | Emergency access: island-native service (browser portal, incident desk, LIS) with optional upstream routes (NG112, PEMEA) | Draft v2 |
| [0005](rfc-0005-island-identity.md) | Island identity, registry allocations, turnkey non-interference (`island-init`) | Draft |
| [0006](rfc-0006-island-console.md) | Island Console: map-based coverage planning, configuration UI, inter-island coordination | Draft |
