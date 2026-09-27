#!/usr/bin/env python3
"""Build bridges only; the deployer's CLI is mounted, never bundled."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biosim_operator.study_container import ensure_operator_image

if __name__ == "__main__":
    ensure_operator_image()
