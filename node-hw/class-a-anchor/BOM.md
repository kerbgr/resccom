# Class A community anchor — design sketch (WBS 2.4)

Paper design until a pilot partner exists (WBS 5.1). Permanent, association-owned, village-scale: 500+ users, full services (NOMAD with full libraries + local LLM, Matrix, Jitsi, PEMEA AP), federation hub for nearby islands. Current state: [STATUS.md](../../STATUS.md).

Directional choices (to be validated with the pilot site):

- **Compute:** fanless server-class (≥64 GB RAM, ≥4 TB NVMe), optional GPU for the local LLM — sized against NOMAD's own recommendations. <!-- VERIFY NOMAD's current AI hardware guidance -->
- **Radio:** COTS O-RAN-compatible small cells rather than SDRs — stability and EIRP headroom; 1–3 sectors per site. Candidate vendors/models tracked here once evaluated. <!-- VERIFY current small-cell options compatible with srsRAN/Open5GS deployments -->
- **Power:** solar array + LiFePO₄ bank sized per [power/](../power/README.md); **donated Tesla Powerwall is a supported profile** (integrated solar inverter, islanding) under the dumb-mode rule — node must never depend on the Tesla cloud (RFC-0001 D10). Open/repairable design remains the reference.
- **Backhaul:** satellite + 5/60 GHz PtP to neighbor islands; QoS per stack/backhaul.
- **Siting:** mast/rooftop height vs. coverage, lightning protection, physical security, and the boring civil-works details that decide real availability — all captured from the pilot, not invented here.
