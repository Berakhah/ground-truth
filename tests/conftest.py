"""Pytest configuration."""

import sys
from pathlib import Path

# Add the project root to sys.path so tests can import from ground_truth
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
