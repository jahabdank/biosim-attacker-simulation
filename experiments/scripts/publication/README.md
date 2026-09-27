# Offline trace publication tools

Original tool code and synthetic tests are MIT licensed. Generated cleaned-trace contributions and original release documentation are CC BY 4.0, subject to third-party exceptions. The tools use Python 3.10+ and PyYAML 6; tests use pytest. They do not import the experiment runtime, contact models, fetch artifacts, or modify the source archive.

Install the publication dependencies and run modules from the experiment repository root:

```sh
python -m pip install -e '.[publication]'
```

The `dev` extra includes these dependencies for the full test suite. Configure these environment variables locally; never commit their private values:

- `ARCHIVE_ROOT`: immutable source archive.
- `PRIVATE_STATE`: private provenance directory outside both public repositories and the source archive.
- `POLICY_FILE`: private JSON policy, also outside public repositories.
- `RESULTS_ROOT`: fresh data-only destination, empty except for an optional `.git` directory.
- `EXPECTED_CANDIDATES`: independently reviewed selected-inventory count.

## Selection

    python -m scripts.publication.selection --source-root "$ARCHIVE_ROOT" --private-report "$PRIVATE_STATE/selection-review.json"

The report contains private paths, hashes, and redaction directions; stdout contains only counts and reason codes. Only `TRACE-REVIEW.grok-4-7-high.md` with reviewer `grok-4.7-high` is accepted. Both disqualification and unsafe-content flags must explicitly be false. Duplicate keys, ambiguous values, aliases, conflicting references, contradictory completion records, and conflicting duplicate decisions fail closed. Reused cell names are not duplicates. Equal outcome/transcript bytes are deduplicated only when other frozen evidence also agrees.

## Private policy

The JSON policy has `schema_version: 1` and these fields:

- `model_labels`: exact source model label to accurate public model label. Every encountered label, including requested labels, must be mapped explicitly; no family/version guessing occurs in the exporter.
- `replacements`: objects with `literal`, `replacement`, and an optional neutral `category`. Use this for consistent crew pseudonyms and known personal/infrastructure identifiers. Longest literals are replaced first.
- `patterns`: optional private regular-expression rules with `pattern`, neutral `category`, and optional `replacement`.
- `review_actions`: keyed by the private SHA-256 digest of each selected review. Each entry requires `approved: true` and all baseline `actions`: `paths`, `hosts`, `crew`, `session_ids`, `credentials`, `personal_identifiers`, `operations`. It can retain private `instructions` and `review` references. Optional per-review `replacements` and `patterns` are actually applied in addition to the baseline.

Approval of an action record means the custodian has translated that review's directions into the baseline/private rules. Merely listing an action is not a substitute for resolving specific directions. Missing approval, unsupported actions, unmapped models, and replacement-key collisions produce explicit private holds. Keep real names/signatures out of public configuration examples and tests.

## Fresh export

    python -m scripts.publication.export --source-root "$ARCHIVE_ROOT" --private-dir "$PRIVATE_STATE" --policy "$POLICY_FILE" --output "$RESULTS_ROOT" --expected-candidates "$EXPECTED_CANDIDATES"

`--source-root` can repeat; its order is part of pseudonym identity. `--scratch-dir` optionally selects a disposable staging parent. The default is the system temporary directory. Only cleaned data is staged. There is no append/cache mode, raw copy, or external script-path fallback. The destination must be fresh. Existing provenance is not overwritten; a later release needs a new private directory, optionally copying the prior private key for stable pseudonyms.

The command binds reviews and consumed sources to private original-byte hashes, applies the policy to all exposed text and keys, and checks public counts/references/hashes before copying the cleaned candidate. Partial or held episodes and orphan assets are removed only from the tool's temporary cleaned tree. Originals and previous exports remain untouched. The private directory receives selection, provenance, additional holds, redaction accounting, and public-verification records. None belongs in a public repository.

Returned `selected`, `exported`, and `additional_holds` counts must reconcile. A successful invocation can contain documented holds; it does not imply every selected candidate was publishable. Read the private hold report and public `COVERAGE.json` before release approval.

## Verification

Public files and reference/count/hash closure:

    python -m scripts.publication.verify --output "$RESULTS_ROOT"

Independent source-level fidelity, including re-selection, source bindings, ordered event fields/ticks/results/exposure, watch states, visible channels, metadata, and frozen inputs:

    python -m scripts.publication.verify --output "$RESULTS_ROOT" --private-dir "$PRIVATE_STATE" --policy "$POLICY_FILE" --report "$PRIVATE_STATE/fidelity.json"

Synthetic regressions, without runtime imports or generated caches:

    PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/publication

The verifier reconstructs expected public evidence independently of the exporter, but shares the explicit privacy policy. Synthetic invariants test nonprivate numeric/text preservation and reject mutations; a separate custodian audit must still assess the policy itself and residual identifying prose. No automated tool establishes universal anonymity, causal attack success, or third-party rights clearance. These tools prepare local candidates, not remote-publication authorization.

## Version 2 source and verification contract

Version 2 publishes `SOURCE-SCHEMA.json` alongside the public JSON schemas. It enumerates retained fields, mapped fields, and justified private omissions for outcome, setup, card, prompt, watch, event, context/compaction, and response records. Unclassified source fields are held with their field names in private diagnostics. Retained measurement trees keep all nonprivate descendants. Recorded temperature, initial habitat state, cell factors, card settings, context-window/compaction measurements, response step counts, and stop conditions are preserved; missing optional settings are not fabricated.

Setup and outcome timeline markers are replaced by references only after full canonical raw-payload equality has been checked. Both markers must occur exactly once. Source verification independently rechecks marker equality, schema coverage, scientific numeric leaves without sanitizing their values, all duplicated index fields, and coverage counts. A checksum refresh cannot legitimize contradictory index metadata or hidden nested files. Only the root `MANIFEST.json` and root Git metadata are exempt from payload hashing; nested reserved names are rejected.

Typed stream records are dispatched by their type even when a single record is valid whole-file JSON. Private channels cannot become visible text merely by containing a `text` key. Structured credential names are normalized explicitly, including client secrets, secret keys and API tokens, without substring deletion of scientific keys. Known private names are checked across filename delimiters, and only the supported frozen component names are accepted. Basic authorization requires authentication context; scientific rate units are distinguished from path references.

A selected episode may be held when a newly retained context-model label has no explicit public mapping. Do not infer that label from the episode model or weaken the schema to reach an expected count. Source verification checks the justification of holds; an unsupported or unreproducible hold is a verification failure, not an all-clear.

Generate a separate fresh candidate and private provenance directory for version 2. A privately copied prior pseudonym key preserves episode/cohort/route identifiers; sanitized asset hashes can change when transformations or retained evidence change. The current verifier targets the version 2 schema. Do not rewrite an older candidate while it is being independently audited; promotion remains a separate owner action.
