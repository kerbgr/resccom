# Governance

## Today

ResCCOM is maintained by its founder, funded personally, developed largely with AI coding agents against public task files and reviewed by re-running the evidence ([README](README.md) "How the project works"). Decisions of substance are made in writing as RFCs ([rfcs/](rfcs/README.md)); anyone can propose one. There is no company behind the project and no plan for one.

## Where it is meant to go

The project's purpose — communities able to communicate and reach help when infrastructure fails — is not well served by a single maintainer forever. The intended path:

1. **Partner labs run islands** ([docs/partner-labs.md](docs/partner-labs.md)). Each lab that federates an island gains a voice in RFC decisions proportional to what it has verified, not what it has promised.
2. **A steering group** forms once three or more islands federate: maintainer plus one representative per island, deciding RFC acceptance by rough consensus, with the founding principles in [RFC-0001](rfcs/rfc-0001-architecture.md) (offline-first, association-owned, upstream-first, honest threat model, no vendor dependency) treated as constitutional — changeable only by a new RFC that explicitly supersedes them.
3. **NGO stewardship.** The goal is for a non-profit with a civil-protection or humanitarian mandate to hold the project's name, repository, and registry ([RFC-0005](rfcs/rfc-0005-island-identity.md)), so that funding, liability, and continuity do not rest on one person. Until then, the maintainer holds them in trust and commits to transferring them to such a body rather than to any commercial owner.

## Commitments that hold regardless of who leads

- The code stays open source (Apache-2.0 for project glue; upstream components under their own licences), and the repository stays public.
- No feature exists to hide a network or its users; lawful, openly operated deployment is a design principle, not a policy ([SECURITY.md](SECURITY.md)).
- Claims are backed by verify scripts and measurements, or they are not made ([STATUS.md](STATUS.md)).
- Nothing in this project is sold as a service by the project; associations own and run their islands ([RFC-0001](rfcs/rfc-0001-architecture.md) D7).

## Practicalities

- Contributions are accepted under the project licence via pull request ([CONTRIBUTING.md](CONTRIBUTING.md)); no contributor licence agreement is required beyond that.
- Security reports: [SECURITY.md](SECURITY.md).
- If the maintainer becomes unable to continue, any partner lab may fork and continue under the same name and principles; this document is the permission.
