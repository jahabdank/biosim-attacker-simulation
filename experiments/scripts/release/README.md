# Release privacy verification

`audit_privacy.py` scans filenames, text, generated artifacts, and symlink boundaries. It reports rule identifiers and locations while withholding matched values. It uses only the Python standard library.

Run it from `experiments/` in the consolidated repository:

```bash
python scripts/release/audit_privacy.py . --report /tmp/runtime-privacy.json
python scripts/release/audit_privacy.py ../simulator --report /tmp/simulator-privacy.json
python scripts/release/audit_privacy.py ../results --report /tmp/results-privacy.json
```

ZIP contents are binary to the filename/text scanner. Verify and extract the cleaned release with `python -m scripts.publication.archive verify --root ../results --extract-to /absolute/private/empty-directory`, then scan the extracted `results/` tree independently before any public distribution.

Exit status is `0` for a completed scan without findings, `1` for findings requiring review, and `2` for invalid or inaccessible input. Detailed reports belong in a private review location. A scan's findings can themselves identify private filenames.

## Private signatures

Supply project-specific identifiers from a file outside the release repositories:

```bash
python scripts/release/audit_privacy.py . \
  --private-rules ../private-release-rules.json \
  --report /tmp/runtime-private-review.json
```

The policy accepts JSON arrays named `literals` and `patterns`. Literal matching is case-insensitive; patterns are Python regular expressions. Keep actual identifying names, organizations, hostnames, and private source paths in that private policy. Public test cases should use synthetic values.

## Independent secret scanning

Use an independently obtained and checksum-verified secret scanner as an additional check. For example, with Gitleaks installed:

```bash
gitleaks dir . --redact=100 --no-banner --ignore-gitleaks-allow \
  --report-format json --report-path /tmp/runtime-secrets.json
gitleaks dir ../results \
  --redact=100 --no-banner --ignore-gitleaks-allow \
  --report-format json --report-path /tmp/results-secrets.json
gitleaks git .. --log-opts=HEAD --redact=100 --no-banner \
  --ignore-gitleaks-allow --report-format json \
  --report-path /tmp/simulator-history-secrets.json
```

Scan the selected release branch's history and all working files. Scan built image layers and any distributed archives separately. Keep those reports private and remove temporary copies after review.

## Review requirements

Check each finding against source provenance. Public upstream copyright notices and attribution can legitimately contain email addresses. Retain legally required notices and record that review explicitly. Correct private-data findings in the release inputs and rerun the checks.

Pattern scans require an independent review of prose, metadata, frozen inputs, and trace transformations. They cannot prove universal anonymity. Combine them with the judge-selection and source-fidelity checks in `scripts/publication/`, and verify that all references and release checksums resolve after changes.
