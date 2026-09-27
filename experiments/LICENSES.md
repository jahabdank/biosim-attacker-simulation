# Licensing and third-party boundaries

## Original contributions

Original experiment Python code, tests, shell scripts, Docker build definitions and launch configuration code are licensed under the MIT terms in `LICENSE`, copyright 2026 BioSim experiment contributors.

Original documentation, original operator/attack/benign prompt contributions, and original narrative protocol descriptions are licensed under Creative Commons Attribution 4.0 International, in `LICENSE-CC-BY-4.0`. Attribute “BioSim experiment contributors,” identify this project/release, link to the license, and indicate modifications. The grant covers only rights the contributors hold.

Cleaned historical trace releases use their own accompanying CC BY 4.0 notice subject to third-party rights. This runtime repository does not grant rights in private reasoning, proprietary services, or another party's generated content merely because it can record such content.

## Inherited material

- BioSim was developed at NASA Johnson Space Center; this runtime uses configurations from the BioSim work maintained by Scott Bell and the TRACLabs package lineage. These credits identify upstream provenance, not endorsement.
- The BioSim simulator in sibling `../simulator` is GPL-3.0, with its original upstream copyright, attribution and embedded notices. Keep `../simulator/LICENSE` and notices, including embedded third-party notices such as the Mersenne Twister license. The Java source and binaries are not relicensed as experiment contributions.
- `configs/*.biosim` derive from BioSim plant configurations. Treat inherited portions as covered by the upstream simulator's GPL-3.0 terms (included in `LICENSE-GPL-3.0`); modifications do not erase upstream rights. Plant catalogs and protocol/prompt files that quote inherited material retain those rights for the quoted portions. Do not describe every asset here as exclusively MIT or CC BY.
- Python packages, container base images and Java/Maven dependencies retain their respective licenses. Installing or constructing an image does not change them. Preserve dependency notices when redistributing built artifacts.
- The external operator CLI is proprietary third-party software supplied legally by the deployer. This repository neither distributes it nor grants a license to it. Container images contain the bridges only; the configured executable is mounted at runtime. Do not redistribute a supplied executable or credentials with the project.
- Public model names identify experimental settings, not endorsement or ownership. Provider terms and rights in model-generated text require separate review before releasing traces.

Privacy substitutions apply to experiment-local identity details, never to legally required upstream notices. The licensing of original contributions is settled; rights not owned by these contributors are not silently licensed by this notice.
