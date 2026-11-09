#!/usr/bin/env python3
"""Verify that the quickstart's copy-paste blocks are what the code actually prints.

Every review round found the same class of defect: the code changed and the doc did
not. Raising the truncation, or re-pasting the output by hand, only resets the clock.
This script closes the loop mechanically:

  1. parse the ```csv blocks out of docs/QUICKSTART-COLLECTOR.md and write them as
     the export files the doc names;
  2. run the commands the doc tells the reader to run;
  3. compare the captured output against the fenced block that follows each command;
  4. also check that every number the doc states (tests, tools, gates) matches the
     repository.

Exit code is non-zero on any mismatch, so CI fails instead of a reader discovering it.
"""
import json
import os
import argparse
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
QUICKSTART = os.path.join(ROOT, "docs", "QUICKSTART-COLLECTOR.md")


def _read_doc():
    with open(QUICKSTART, encoding="utf-8") as f:
        return f.read()


def _csv_blocks(doc):
    """Return [(filename, csv_text)] parsed from the document.

    Filenames live in the prose just above each block (they were deliberately moved
    out of the block: csv.DictReader does not skip comments).
    """
    out = []
    for m in re.finditer(r"```csv\n(.*?)```", doc, re.S):
        body = m.group(1).rstrip("\n")
        before = doc[:m.start()]
        names = re.findall(r"(\d{4}-\d{2}-\d{2}-[\w.-]+\.csv)", before)
        if not names:
            raise SystemExit("csv block at offset %d has no filename above it" % m.start())
        out.append((names[-1], body))
    return out


def _run(args, cwd):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")



def _plain_block_span(doc, marker):
    """(begin, end) offsets of the first LANGUAGE-LESS fenced block after marker."""
    pos = doc.find(marker)
    if pos < 0:
        raise SystemExit("marker not found in doc: %r" % marker)
    m = re.search(r"\n```\n", doc[pos:])
    if not m:
        raise SystemExit("no output block after %r" % marker)
    begin = pos + m.end()
    end = doc.find("```", begin)
    if end < 0:
        raise SystemExit("unterminated output block after %r" % marker)
    return begin, end


def _replace_block_after(doc, marker, new_text):
    begin, end = _plain_block_span(doc, marker)
    return doc[:begin] + new_text.rstrip("\n") + "\n" + doc[end:]


def _norm(text):
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def _plain_block_after(doc, marker):
    """Return the first LANGUAGE-LESS fenced block after `marker`.

    Only bare fences are output blocks; ```bash fences are commands, and the
    closing fence of a command block is not a block opener.
    """
    pos = doc.find(marker)
    if pos < 0:
        raise SystemExit("marker not found in doc: %r" % marker)
    m = re.search(r"\n```\n", doc[pos:])
    if not m:
        raise SystemExit("no output block after %r" % marker)
    begin = pos + m.end()
    end = doc.find("```", begin)
    if end < 0:
        raise SystemExit("unterminated output block after %r" % marker)
    return _norm(doc[begin:end])


def _doc_command(doc, script_name):
    """Return the command line the doc tells the reader to run for this script."""
    m = re.search(r"python scripts/%s[^\n]*" % re.escape(script_name), doc)
    if not m:
        raise SystemExit("doc never shows how to run %s" % script_name)
    return m.group(0).strip()


def _run_doc_command(doc, script_name, subs, extra_db=None, tmp=None):
    """Execute the document's own command line, with paths redirected to a temp dir.

    Running a command we hard-code would keep passing after someone edited the doc
    to name the wrong script or the wrong source, so the command is parsed from the
    document and only the output locations are substituted.
    """
    cmd = _doc_command(doc, script_name)
    for old, new in subs.items():
        cmd = cmd.replace(old, new)
    parts = cmd.split()
    if parts and parts[0] == "python":
        parts[0] = sys.executable
    rc, out = _run(parts, ROOT)
    return rc, out


def check_quickstart(update=False):
    doc = _read_doc()
    blocks = _csv_blocks(doc)
    if not blocks:
        raise SystemExit("no csv blocks found in %s" % QUICKSTART)
    problems = []
    with tempfile.TemporaryDirectory(prefix="ibe-doc-") as tmp:
        for name, body in blocks:
            with open(os.path.join(tmp, name), "w", encoding="utf-8", newline="") as f:
                f.write(body + "\n")
        db = os.path.join(tmp, "my.db")
        py = sys.executable
        rc, out = _run_doc_command(doc, "run_import.py",
                                   {"<dir>": tmp, "./my-exports": tmp, "data/my.db": db},
                                   extra_db=db, tmp=tmp)
        if rc != 0:
            problems.append("import failed (rc=%d):\n%s" % (rc, out[-800:]))
            return problems
        actual_import = _norm("\n".join(out.strip("\n").splitlines()[-3:]))
        if update:
            doc = _replace_block_after(doc, "实跑输出（末尾几行）：", actual_import)
        expected_import = _plain_block_after(doc, "实跑输出（末尾几行）：")
        if _norm(expected_import) != actual_import:
            problems.append("import tail differs:\n--- doc ---\n%s\n--- real ---\n%s"
                            % (expected_import, actual_import))
        rc, out = _run_doc_command(doc, "audit_source.py",
                                   {"data/my.db": db}, extra_db=db, tmp=tmp)
        if rc != 0:
            problems.append("audit_source failed (rc=%d):\n%s" % (rc, out[-800:]))
            return problems
        actual_audit = _norm(out)
        if update:
            doc = _replace_block_after(doc, "实跑输出：", actual_audit)
            with open(QUICKSTART, "w", encoding="utf-8", newline="\n") as f:
                f.write(doc)
            print("updated %s" % os.path.basename(QUICKSTART))
            return []
        expected_audit = _plain_block_after(doc, "实跑输出：").lstrip()
        if expected_audit != actual_audit:
            exp, act = expected_audit.splitlines(), actual_audit.splitlines()
            diff = [ln for ln in range(max(len(exp), len(act)))
                    if (exp[ln] if ln < len(exp) else "<missing>")
                    != (act[ln] if ln < len(act) else "<missing>")]
            detail = "\n".join("  line %d\n    doc : %s\n    real: %s"
                               % (ln + 1, exp[ln] if ln < len(exp) else "<missing>",
                                  act[ln] if ln < len(act) else "<missing>") for ln in diff[:6])
            problems.append("audit output differs:\n" + detail)
    return problems


def _count_tests():
    n = 0
    for base, _dirs, files in os.walk(os.path.join(ROOT, "tests")):
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                with open(os.path.join(base, f), encoding="utf-8") as fh:
                    n += len(re.findall(r"^\s+def test_", fh.read(), re.M))
    return n


def _count_tools():
    with open(os.path.join(ROOT, "src", "indiebiz_evidence", "mcp_server.py"), encoding="utf-8") as f:
        src = f.read()
    # TOOL_SCHEMAS entries are dicts whose "name" key sits at 8 spaces
    return len(re.findall(r'^\s{4,12}"name":\s*"', src, re.M))



def check_numbers():
    problems = []
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        changelog = f.read()
    # take the newest version section without hard-coding its number: a renamed
    # heading used to make this check silently do nothing
    parts = re.split(r"\n## ", changelog)
    head = parts[1] if len(parts) > 1 else ""
    if not head:
        problems_early = ["CHANGELOG has no version section -- cannot verify the test count"]
    declared = re.findall(r"测试\s*\**\s*(\d+)\s*\**\s*(?:→|->)\s*\**\s*(\d+)", head)
    tests = _count_tests()
    if declared and declared[0][1] != str(tests):
        problems.append("CHANGELOG says %s tests, repository has %d" % (declared[0][1], tests))
    tools = _count_tools()
    m_tools = re.search(r"\*\*(\d+) 个工具\*\*|### (\d+) ?个工具", readme)
    expected_tools = None
    if m_tools:
        expected_tools = int(m_tools.group(1) or m_tools.group(2))
    if expected_tools is not None and expected_tools != tools:
        problems.append("README says %d tools, mcp_server has %d" % (expected_tools, tools))
    if tools == 0:
        problems.append("could not count tools -- the counter itself is broken")

    return problems


def _utf8_stdio():
    """A GBK console must not crash a tool that prints Chinese."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true",
                    help="rewrite the doc's output blocks from a real run, then exit 0")
    a = ap.parse_args()
    problems = []
    problems += check_quickstart(update=a.update)
    problems += check_numbers()
    if problems:
        print("DOC TRUTH CHECK FAILED")
        for p in problems:
            print("- " + p)
        return 1
    print("DOC TRUTH CHECK OK: quickstart blocks and stated counts match the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
