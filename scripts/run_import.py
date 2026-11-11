#!/usr/bin/env python3
"""CLI wrapper: import a source. Same as `indiebiz-evidence import`.

Paths are relative to the current working directory.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from indiebiz_evidence import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main(["import"] + sys.argv[1:]))