# Privacy boundaries

Published inputs replace personal crew-display aliases consistently, remove private machine paths and infrastructure labels, and keep model versions and experimental settings distinct from routing. Required legal notices and fictional plant/console identifiers are retained.

Provider URLs, deployment strings, credential paths and optional native subscription authentication are supplied in a local `BIOSIM_PROVIDERS` TOML file. Keep it outside the checkout. No ambient authentication is copied from a user's home directory. API secrets stay in the trusted route process, not the operator container. Native subscription mode necessarily gives its CLI process access to the explicitly supplied authentication copy in episode scratch; it is removed during cleanup.

Run outputs are **private by default**. The original driver records operational paths, timestamps, session identifiers and CLI stdout/stderr for diagnosis and fidelity. Do not publish raw output directories or container inspect output. Apply the separately maintained publication/release tools before sharing traces. The compact compaction record retains counters, not private CLI session summaries.

Keep `.env`, provider configuration, credentials, caches, run records and generated build artifacts out of Git and build contexts. Use disposable clean-room copies for qualification. Do not include source-history reports, private source mappings, or anonymization keys in this repository.

Sanitation changes prompt bytes. Public digests identify sanitized inputs, not the private originals. Retained language or behavioral patterns may still allow inference; automated scanning is not a guarantee of anonymity. Independent release review is required.
