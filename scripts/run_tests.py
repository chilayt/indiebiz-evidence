#!/usr/bin/env python3
"""Test runner that FAILS on skips (review P0-1: skipped tests = fake green CI).

Exit code 0 only when: all tests ran, none failed, none errored, none skipped.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(PROJECT_ROOT, "tests"))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    problems = len(result.failures) + len(result.errors) + len(result.skipped)
    if result.skipped:
        print("\nFAIL: %d test(s) were SKIPPED -- skips are treated as failures "
              "(a clean clone must run every test against the demo DB)." % len(result.skipped))
    if not result.wasSuccessful() or problems:
        sys.exit(1)
    print("\nOK: %d tests ran, 0 failures, 0 errors, 0 skipped." % result.testsRun)
    sys.exit(0)


if __name__ == "__main__":
    main()
