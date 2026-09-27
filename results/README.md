# BioSim cleaned experimental traces

This is a **local publication candidate**, not a raw archive. Only episodes passing the selected latest judge's two eligibility flags are included. The candidate contains successful and unsuccessful attacks, controls, and other historical arms; inclusion never depends on crew survival or qualitative interest.

See `COVERAGE.json` for exact selection/export counts and holds, `index.json` for episodes, `SCHEMA.md` for interpretation, and `PRIVACY.md` for transformations. `MANIFEST.json` hashes every reconstructed release file except itself; `ARCHIVES.json` hashes the ZIP shards and records which episode each contains. This archive README describes the package; extraction restores the source release's original README.

`ARCHIVES.json` maps each of 720 complete episodes to one of 31 checked ZIP shards (each under 8 MB). After extraction, each episode contains an outcome record, an ordered `events.jsonl` timeline, and watch states with visible responses. Shared `inputs/` and `attacks/` contain only referenced, sanitized frozen artifacts. `MANIFEST.json` describes the reconstructed files and preserves the source release's integrity evidence. No previous export is grandfathered into this candidate.

Do not pool cohorts merely because model labels match. A death is not proof of a successful injection; zero deaths are not proof of resistance. Exposure, held actuation, restoration, procedural behavior, and crew outcomes are distinct measurements. Incomplete or unreviewed attempts remain outside this repository.

## Offline verification

From `experiments/` in this repository, verify the ZIP inventory and extract into a new directory:

    .venv/bin/python -m scripts.publication.archive verify --root ../results --extract-to /absolute/private/new-extraction-directory

This command checks the ZIP and member hashes, reconstructs `new-extraction-directory/results/`, and checks all 720 episodes against the release file manifest, event/watch counts and references. Repeating the public check is optional:

    .venv/bin/python -m scripts.publication.verify --output /absolute/private/new-extraction-directory/results

Verification can take minutes on slower disks. A custodian can additionally supply `--private-dir PRIVATE_PROVENANCE --policy PRIVATE_POLICY` for source-level fidelity verification. Neither private input belongs in this repository. No model access is used.

## Rights and status

The cleaned trace contribution is offered under CC BY 4.0, subject to the exceptions in `THIRD_PARTY.md`. Cleaning does not establish ownership of incorporated material or remove third-party rights. Public distribution requires the custodian's rights and privacy review. These are pseudonymized records, not a guarantee against reidentification.
