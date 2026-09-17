# Spectrum & regulatory matrix (WBS 0.4)

**The single biggest external constraint on this project.** A radiating cellular network requires authorization in every jurisdiction. This matrix tracks, per country: local/private licensing options, test/experimental licenses, costs, and disaster-time emergency provisions. Every cell below is a lead to verify with the regulator's current documents — nothing here is legal advice, and `<!-- VERIFY -->` means exactly that.

## Matrix (launch countries first)

| Country | Regulator | Local/private cellular licensing | Test/experimental | Disaster provisions | Status |
|---|---|---|---|---|---|
| Finland | Traficom | Local 4G/5G licenses (2.3 GHz band area licenses) <!-- VERIFY current band/terms --> | Test licenses available <!-- VERIFY --> | <!-- VERIFY --> | Lead — verify |
| Germany | BNetzA | 3.7–3.8 GHz Campusnetze, application-based, modest fees <!-- VERIFY --> | Versuchsfunk licenses <!-- VERIFY --> | <!-- VERIFY --> | Lead — verify |
| Sweden | PTS | <!-- VERIFY: local licensing status --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |
| Norway | Nkom | <!-- VERIFY --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |
| Denmark | SDFI/Styrelsen | <!-- VERIFY --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |
| Netherlands | RDI | 3.5 GHz local licensing <!-- VERIFY --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |
| UK | Ofcom | Shared Access Licences (3.8–4.2 GHz, 1800/2300 MHz) <!-- VERIFY --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |
| Greece | EETT | <!-- VERIFY --> | <!-- VERIFY --> | <!-- VERIFY --> | Open |

## How to research a country (repeatable recipe)

1. Find the NRA's pages on *local/private networks*, *verticals spectrum*, or *test licenses*; download the current fee schedule and application form.
2. Record: eligible entities (can a nonprofit association apply?), bands, max EIRP, geographic granularity, cost, processing time, renewal.
3. Check emergency provisions: does the NRA have a disaster/temporary-authorization mechanism? Who can invoke it?
4. Add sources (URLs + retrieval date) below the table in a per-country subsection. Update `Status` to `Verified <date>`.

## Non-cellular fallbacks (no license needed, any country)

Wi-Fi (2.4/5/6 GHz within EIRP limits), 868 MHz LoRa/Meshtastic, wired — always legal tiers for citizen deployment while the association's cellular license is in progress. The stack must degrade gracefully to these (Wi-Fi AP mode on every node class).
