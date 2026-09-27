# Trace schema, version 2

`SCHEMA.json` provides public JSON Schema definitions. `SOURCE-SCHEMA.json` documents each source record's retained fields, explicitly mapped fields, and justified private omissions. Unknown source fields are held, never approved merely to reach a target count. Retained measurement trees preserve all nonprivate descendants.

Optional recorded temperature, cell indices, initial habitat state, card settings/identity/plant descriptions, and context-window/compaction measurements are retained. Missing settings are not invented. Context-model labels must be explicitly mapped; unresolved labels are held. Initial setup state is separate from terminal state. Source cell-factor suffixes preserve repeat/treatment labels without exposing the private series/model prefixes.

- `index.json` is the exact exported inventory. Each entry references its outcome, frozen input bundle, and optional attack text.
- `episodes/<episode_id>/outcome.json` records precise public `model` and `model_requested` labels, pseudonymous cohort/route/experiment identifiers, recorded arm/trust/condition, `experiment` parameters, `protocol`, sanitized card evidence, judge selection, counts, and `outcome` measurements. Missing experimental settings are absent, not defaulted to newer values.
- `events.jsonl` preserves source event order with contiguous one-based `sequence`, source event type, and its allowed scientific fields. Tool rows retain actual `ticks`, arguments, result, optional score, and S-band exposure/frame metadata. Exactly one setup and one outcome marker are required. Each full canonical raw marker payload must equal its referenced standalone record before a reference is emitted; disagreements are held. `event_count` counts all rows; `tool_event_count` counts only `event: tool` rows.
- `watches/<turn>.json` retains recorded states, scores, query, return code, timeouts, tool summaries, and recovery indicators. `response` contains `availability`, `format`, final visible `text`, and ordered visible assistant `messages`. Empty responses are not fabricated; JSONL thinking events are omitted. Final text may repeat the last message because these are distinct source fields.
- `inputs/input-<public hash>.json` preserves relevant frozen Markdown, console rules (`.mdc`), and `prompts.json` fields. Source signature files are not published. `attacks/attack-<public hash>.txt` is the cleaned episode-local attack snapshot, not a mutable external script.

Cohort identifiers group source batches; route identifiers distinguish source batch/model/harness combinations. They do not certify identical backend endpoints, model revisions, or providers. Reused cell names are not a deduplication key. Exact outcome/transcript duplicates are checked against their other frozen evidence before collapse.

`judge` is a sanitized eligibility record, not the full private review or a causal success label. All required privacy actions are applied regardless of whether a particular review repeats them. Boolean false is explicit; missing or ambiguous judgments are never treated as false.

Redaction markers identify transformations, not original model language. Numeric scientific values and relative simulator time are retained. Sanitization is not byte identity; public hashes cover only cleaned artifacts. Raw-source bindings and omitted-field accounting remain private.
