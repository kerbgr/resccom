# node-hw — hardware reference designs (WBS 2.x)

Three node classes, one software image (RFC-0001 D9). Each class dir holds `BOM.md` (parts, sources, prices — all prices `<!-- VERIFY -->` until quoted), build notes, and a field-setup guide. Nothing here is built yet; BOMs start as engineering targets.

```mermaid
flowchart TB
    subgraph classc["Class C — backpack (≤30 W)"]
        C1["N100 mini-PC / Pi 5"] --- C2["LimeSDR-class SDR"] --- C3["Battery + fold-out solar"]
    end
    subgraph classb["Class B — vehicle (~150 W)"]
        B1["Rugged mini-ITX"] --- B2["USRP B210 + mast antenna"] --- B3["Vehicle DC / genset / solar"] --- B4["Starlink Mini"]
    end
    subgraph classa["Class A — anchor (community)"]
        A1["Fanless server (+ optional GPU for local LLM)"] --- A2["COTS small cell(s), sectorized"] --- A3["Solar array + LiFePO4 bank<br/>or donated Powerwall profile"] --- A4["Satellite + PtP backhaul"]
    end
    IMG["One node OS image (WBS 2.1)<br/>Debian + compose, per-class profile"] --> classc & classb & classa
```

| | Class C | Class B | Class A |
|---|---|---|---|
| Scenario | First hours of a disaster | Rapid-deploy ops | Permanent community anchor |
| Setup time target | 15 min, one person | 4 h, two people | Planned install |
| Power budget | ≤30 W | ~150 W | Sized per site ([power/](power/README.md)) |
| Radio | Low-cost SDR, low EIRP | B210 + mast | COTS small cells |
| Services | Matrix, maps, portal | Full minus GPU LLM | Everything + PEMEA AP + federation hub |
| Dir | [class-c-backpack/](class-c-backpack/BOM.md) | [class-b-vehicle/](class-b-vehicle/BOM.md) | [class-a-anchor/](class-a-anchor/BOM.md) |

**Order of work:** power engineering ([power/](power/README.md)) and Class C BOM first — Class C is the cheapest to get wrong and the most constrained, so it disciplines the image (WBS 2.1). Class A stays a paper design until a pilot partner exists (WBS 5.1).
