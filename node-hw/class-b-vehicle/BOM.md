# Class B vehicle / rapid-deploy — Bill of Materials (WBS 2.3)

Engineering target, no build yet. Target: two people to on-air in under 4 hours, ~150 W, ~200 users at 1–2 km, full service stack minus GPU LLM. Current state: [STATUS.md](../../STATUS.md).

| # | Part | Candidate | Est. cost | Notes |
|---|---|---|---|---|
| 1 | Compute | Rugged fanless mini-ITX, 32 GB RAM, 1 TB NVMe | €700 <!-- VERIFY --> | |
| 2 | SDR | Ettus USRP B210 | €2,100 <!-- VERIFY --> | The reference radio (stack/ran 1.2-c); used-market guidance welcome |
| 3 | RF front-end | PA/LNA/duplexer per licensed band | €400 <!-- VERIFY --> | |
| 4 | Antennas + mast | Sectoral or high-gain omni, 6–10 m pump-up mast, guying | €600 <!-- VERIFY --> | |
| 5 | Power | Vehicle 12/24 V DC-DC + LiFePO₄ 100 Ah buffer + optional 200 W solar | €500 <!-- VERIFY --> | Genset input documented, not included |
| 6 | Backhaul | Starlink Mini + mount | €350 <!-- VERIFY --> | Bypass-mode profile per stack/backhaul 1.4-d |
| 7 | Networking | 5-port industrial switch, cabling, grounding kit | €150 <!-- VERIFY --> | |
| 8 | Cases | Transport cases, weatherproofing | €300 <!-- VERIFY --> | |
| 9 | SIM kit | 50× programmable SIMs + reader + label printer | €250 <!-- VERIFY --> | Batch mode: sim-tools 3.2-d |

**Deployment drill target (documents itself as `DRILL.md` after first exercise):** unload → mast up → radiate (licensed) → first phone attached → portal reachable, timed. The 4-hour claim becomes real only when a drill logs it.
