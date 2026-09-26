#!/usr/bin/env python3
"""Partial stdout, then hang. Used by timeout E2E tests. No network."""
import sys
import time

sys.stdout.write("PARTIAL-BYTES-BEFORE-HANG\n")
sys.stdout.flush()
time.sleep(3600)
