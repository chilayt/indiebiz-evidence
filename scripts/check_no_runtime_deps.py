#!/usr/bin/env python3
"""Zero runtime dependencies is a product promise; verify it instead of claiming it.

Two levels:
  default      pyproject.toml declares no runtime dependencies and the package
               imports nothing outside the standard library
  --installed  the actually installed distribution also reports none
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "src", "indiebiz_evidence")


def declared_deps():
    try:
        import tomllib
    except ImportError:  # python 3.9/3.10
        tomllib = None
    path = os.path.join(ROOT, "pyproject.toml")
    if tomllib is None:
        text = open(path, encoding="utf-8").read()
        for line in text.splitlines():
            if line.strip().startswith("dependencies"):
                return line.split("=", 1)[1].strip()
        return "?"
    with open(path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project") or {}
    return project.get("dependencies") or []


def imported_roots():
    roots = set()
    for name in sorted(os.listdir(PKG)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(PKG, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    roots.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    roots.add(node.module.split(".")[0])
    return roots


def main(argv=None):
    argv = argv or sys.argv[1:]
    problems = []
    deps = declared_deps()
    if isinstance(deps, list) and deps:
        problems.append("pyproject declares runtime dependencies: %r" % (deps,))
    elif isinstance(deps, str) and deps not in ("", "[]", "?", "()"):
        problems.append("pyproject declares runtime dependencies (unparsed form): %r" % (deps,))
    # standard library only
    # sys.stdlib_module_names exists from 3.10. On 3.9 the fallback list must be
    # complete enough not to accuse the package of depending on itself: __future__
    # and unicodedata were reported as third-party, which would fail CI on 3.9.
    if hasattr(sys, "stdlib_module_names"):
        stdlib = set(sys.stdlib_module_names)
    else:
        stdlib = {
            "__future__", "abc", "argparse", "array", "ast", "base64", "binascii",
            "bisect", "builtins", "bz2", "calendar", "cmath", "codecs", "collections",
            "colorsys", "configparser", "contextlib", "copy", "csv", "ctypes",
            "datetime", "decimal", "difflib", "dis", "email", "enum", "errno",
            "faulthandler", "filecmp", "fileinput", "fnmatch", "fractions",
            "functools", "gc", "getopt", "getpass", "gettext", "glob", "gzip",
            "hashlib", "heapq", "hmac", "html", "http", "imaplib", "importlib",
            "inspect", "io", "ipaddress", "itertools", "json", "keyword", "linecache",
            "locale", "logging", "lzma", "mailbox", "math", "mimetypes", "mmap",
            "numbers", "operator", "os", "pathlib", "pickle", "pkgutil", "platform",
            "plistlib", "pprint", "profile", "pstats", "pty", "queue", "quopri",
            "random", "re", "reprlib", "secrets", "select", "shelve", "shlex",
            "shutil", "signal", "smtplib", "socket", "sqlite3", "ssl", "stat",
            "statistics", "string", "struct", "subprocess", "sys", "sysconfig",
            "tarfile", "tempfile", "textwrap", "threading", "time", "timeit",
            "token", "tokenize", "traceback", "types", "typing", "unicodedata",
            "unittest", "urllib", "uuid", "venv", "warnings", "wave", "weakref",
            "webbrowser", "xml", "xmlrpc", "zipfile", "zipimport", "zlib",
        }
    third = sorted(r for r in imported_roots() if r not in stdlib and r != "indiebiz_evidence")
    if third:
        problems.append("package imports non-stdlib modules: %r" % (third,))
    if "--installed" in argv:
        try:
            from importlib.metadata import requires
            reqs = requires("indiebiz-evidence") or []
            hard = [r for r in reqs if "extra ==" not in r]
            if hard:
                problems.append("installed metadata requires packages: %r" % (hard,))
        except Exception as e:
            problems.append("cannot read installed metadata: %r" % (e,))
    if problems:
        for p in problems:
            sys.stderr.write("DEPENDENCY CONTRACT BROKEN: %s\n" % p)
        sys.stderr.write("\nZero runtime dependencies is documented in README and COMPLIANCE.\n"
                         "If a dependency is genuinely required, change those documents first.\n")
        return 1
    print("dependency contract OK: no runtime dependencies declared, imported or installed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
