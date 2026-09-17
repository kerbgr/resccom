# Class C backpack — Bill of Materials (WBS 2.2)

Engineering target, no build yet. Every price and part is a candidate until purchased and tested; keep `<!-- VERIFY -->` markers until then. Target: ≤30 W total draw, one-person carry, 15-minute setup, ~50 users at ~300–500 m. Current state: [STATUS.md](../../STATUS.md).

| # | Part | Candidate | Est. cost | Notes |
|---|---|---|---|---|
| 1 | Compute | Intel N100 mini-PC, 16 GB RAM, 512 GB NVMe | €200 <!-- VERIFY --> | Pi 5 fallback if power budget forces it |
| 2 | SDR | LimeSDR Mini 2.0 or successor | €400 <!-- VERIFY --> | Gate on `stack/ran` 1.2-d finding |
| 3 | RF front-end | Band-appropriate PA/LNA + duplexer per licensed band | €150 <!-- VERIFY --> | Depends on country/license — see [docs/spectrum/](../../docs/spectrum/README.md) |
| 4 | Antennas | 2× omni, band-matched, SMA | €60 <!-- VERIFY --> | |
| 5 | Battery | LiFePO₄ 12 V ≥30 Ah + BMS | €150 <!-- VERIFY --> | ~8 h at full draw — see [power/](../power/README.md) |
| 6 | Solar | 100 W foldable + MPPT charge controller | €180 <!-- VERIFY --> | |
| 7 | DC wiring | 12 V bus, USB-PD trigger for compute, fusing | €40 <!-- VERIFY --> | Bus conventions in [power/](../power/README.md) |
| 8 | Enclosure | Hard case or purpose backpack, padded, vented | €100 <!-- VERIFY --> | |
| 9 | SIM kit | 10× programmable SIMs + USB PC/SC reader | €80 <!-- VERIFY --> | Programmed via [sim-tools](../../sim-tools/TASKS.md) |

**Open questions:** LimeSDR viability (1.2-d), realistic EIRP/coverage under a low-power license, thermal behavior sealed in a pack. Answers come from builds, not estimates.

**Build log:** none yet. First build appends dated notes here; the field-setup guide becomes `SETUP.md` after build #1.
