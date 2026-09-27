# Complete historical experiment code inventory

This is a **code archive**, not a private run archive and not a second default runtime. It preserves the available reference runtime modules, launchers, adapters, preparation/measurement helpers, study controllers, tests, and Docker/bridge definitions, plus all comparison-directory Python launchers. `inventory.json` enumerates every consumed file, public digest, defined functions/classes and imports. Original paths and private deployment bindings remain outside this repository.

`runtime/configs`, `runtime/packs`, `runtime/data` and the protocol directories are repository-internal links to the complete public input sets. They cannot drift into a second, inconsistently sanitized copy. The six XML files retain original simulator vocabulary, including `NUCLEAR`, `Nuclear_Source`, and `NuclearPowerPS`.

## Preserved treatments

- Original static screen/discovery/grid/stage definitions, including v23–v39 launch scripts where available.
- Separate-duty/shared-duty designs, T0/T1/T2/unlabeled follow-ons, original 16-turn GPT-6 pilots, later recovered-watch protocols, controls, sequencing and prior-attempt lineage logic.
- Native Grok and routed Grok remain distinct. `grok-4.6-route-a` identifies the 200,000-context routed cohort; it is not an alias for the 500,000-context native subscription.
- The v32/v33/v34 adaptive-writer builders, `attacker.py`, the original driver feedback loop, writer briefs, writer model assignments, and live generated-beat handling are retained. Adaptive generation consumes prior operator/plant observations; **frozen writer-produced text is not an equivalent treatment**.
- Original available Cursor/Hermes/Grok adapters and entrypoint scripts are included. Proprietary executables, user authentication, unavailable machine-specific operator configurations, private historical results and private gateways are not included or invented.

Seven files concerned solely with machine migration, privilege policy, private databases and host cutover are explicitly listed as `excluded-machine-administration`. Their functions do not define experiment cells or scientific treatments. Nothing else in the consumed source-code inventory is silently omitted.

## Default is inert

Every archived Python file has an import-time gate; archived shell helpers also fail closed. Neither importing an archived launcher nor running it with `--help` executes its original module setup by default. Do not add `historical/runtime/src` to normal PYTHONPATH or collect archived tests as current runtime regressions. The normal package and launch commands continue to use the corrected runtime in `src/`.

The gate requires all of:

1. `BIOSIM_ARCHIVE_ENABLE=1`;
2. `BIOSIM_ARCHIVE_CONFIG` naming a deployer-supplied TOML file with `[execution] allow_side_effects = true`;
3. `BIOSIM_ALLOW_LIVE=1`.

These settings authorize potentially unsafe historical side effects and model calls; **do not set them merely to inspect definitions**. Use static source inspection and the tests that extract only named pure scientific builders instead. No charged inference is needed to inspect or validate the archive.

Private absolute paths and private endpoint defaults in Python are replaced by `_archive_path`/`_archive_setting` bindings. Required binding names/types and use sites are listed in `inventory.json`; supply values locally under `[settings]`. No private original-value map is shipped.

Gateway host and port bindings are independent for each route; no historical port-sharing arrangement is implied. Hosts are configured hostnames/IP addresses, and `_archive_port` requires a decimal string in the range 1–65535. Bindings of type `credential_file` name local files containing one nonempty raw credential; `_archive_credential` reads them without an embedded fallback or diagnostic disclosure. Keep these files and deployment bindings outside the repository. API paths, model/context settings, pacing, public simulator ports and explicitly synthetic fixtures are unchanged. Shell/install helpers require manual deployment review as well; they are preserved historical code, not endorsed installation procedures.

## Execution and fidelity limits

Availability of the original code is not a claim that current CLI versions, remote services, old operator configurations or unavailable prior-run records can reproduce historical outcomes. Some historical controllers require previous results; those are explicit external inputs, not fabricated empty success states. Host-only seating and dynamic-writer execution are not silently promoted into the supported isolated runtime. Requalify a reviewed deployment before deliberately enabling them.

The archive retains historical failure behavior for study/provenance review, including defects corrected in the default runtime. Do not use it to bypass current mutation acknowledgement, timeout quiescence or privacy fixes. Source algorithms are preserved apart from privacy-neutral names, explicit deployment bindings and the execution gate; mandatory legal notices remain governed by `../LICENSES.md`.

## Portable earlier cohorts

The top-level manifests now also include native/routed-200k Grok T0 follow-ons, Luna/Sonnet T0 follow-ons, native Grok 16-turn unlabeled triples, Terra/Sol T0 and unlabeled triples, and GPT-6 16-turn pilot triples. Each points to its preserved definition. Tests compare generated job order, stories, repetitions, identities, separators, context and pacing to the archived builder functions, rather than asserting only aggregate counts.
