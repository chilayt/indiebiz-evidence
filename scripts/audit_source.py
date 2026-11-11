#!/usr/bin/env python3
"""CLI wrapper: one-shot health report. Same as `indiebiz-evidence audit`.

The logic lives in the package (indiebiz_evidence.reporting) so it also works
after `pip install`, from any directory.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from indiebiz_evidence import reporting  # noqa: E402

if __name__ == "__main__":
    sys.exit(reporting.main())