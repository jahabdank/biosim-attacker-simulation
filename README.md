# BioSim attacker simulation — conference artifact

This repository contains the fixed Java simulator, the experiment runtime and the cleaned, judge-approved trace release together. The article manuscript and private operational data are separate and are not distributed here.

| Directory | Contents | Start here |
|---|---|---|
| [`simulator/`](simulator/) | BioSim Java source, GPL-3.0 and upstream notices | [`simulator/README.md`](simulator/README.md) |
| [`experiments/`](experiments/) | Experiment code, identity packs, manifests, Docker setup and offline qualifications | [`DEPLOY.md`](DEPLOY.md), [`experiments/MODELS.md`](experiments/MODELS.md) |
| [`results/`](results/) | Cleaned approved traces in checked ZIP shards plus a readable index and source manifest | [`results/README.md`](results/README.md) |

## Quickstart

Read [`DEPLOY.md`](DEPLOY.md) to build the simulator, run the automated suite and execute one offline control through the original episode loop. Offline mode uses a deterministic fake operator and requires no model account or provider access. It does not reproduce historical model outputs. Adding an API-compatible model is described in [`experiments/MODELS.md`](experiments/MODELS.md) and needs an independently supplied provider configuration and credential.

The results are a fixed 720-episode, judge-approved, pseudonymized release. Run `python -m scripts.publication.archive verify --root ../results --extract-to /absolute/private/new-directory` from `experiments/` to check every archive and extract a complete release into `new-directory/results/`. This command also runs the original file-manifest, reference, episode-count and evidence checks. The archive inventory ties individual ZIPs and episode IDs to the source `results/MANIFEST.json` checksums. Details and limits are in [`results/SCHEMA.md`](results/SCHEMA.md) and [`results/PRIVACY.md`](results/PRIVACY.md).

## Provenance and boundaries

The included simulator derives from BioSim, developed at NASA Johnson Space Center with the public Scott Bell / TRACLabs package lineage retained in upstream notices. This fixed simulator source and the experiment runtime are self-contained in this artifact. The trace release preserves its original SHA-256 file manifest and a separately checked ZIP inventory. Historical source-commit identifiers and private source mappings are held by the custodian outside the conference artifact; they are not required to build or verify it.

`simulator/` retains its GPL-3.0 and inherited notices. Original experiment code is MIT; original documentation and contributions to trace cleaning use CC BY 4.0 subject to incorporated third-party rights. See [`experiments/LICENSES.md`](experiments/LICENSES.md) and [`results/THIRD_PARTY.md`](results/THIRD_PARTY.md). Do not relicense upstream code, model outputs or inherited prompts by treating this repository as one license.

The release excludes private credentials, provider endpoints, local machine paths, raw results and operator session histories. Experiment runs produce private output and require a fresh privacy review before sharing. Textual or behavioral fingerprints can still support linkage; pseudonymization is not proof against reidentification. The published ZIPs contain cleaned bytes as-is; a repository anonymization service does not rewrite their contents. Review the anonymized download and run the integrity checks before sharing an anonymous link.
