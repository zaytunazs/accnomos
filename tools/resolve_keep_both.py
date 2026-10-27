"""Resolve 'both added' conflict hunks by keeping HEAD then THEIRS, in every conflicted file git reports.

Usage: python tools/resolve_keep_both.py [--table-first]
Safe only for additive conflicts (new rows, imports, routers, cards). Prints the files it touched; refuses hunks where both sides
modify the same line (same first line) so a human can look.
"""
import re, subprocess, sys

HUNK = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)

def resolve(text: str, path: str) -> str:
    def f(m):
        head, theirs = m.group(1), m.group(2)
        h1 = head.strip().splitlines()[:1]; t1 = theirs.strip().splitlines()[:1]
        if h1 and t1 and h1 == t1:
            raise SystemExit(f"{path}: both sides change the same line; resolve by hand")
        # README-style: keep table rows together before prose blocks
        if path.endswith("README.md") and head.lstrip().startswith("|") and theirs.lstrip().startswith("|"):
            h_rows, _, h_rest = head.partition("\n\n")
            return h_rows + "\n" + theirs.rstrip("\n") + "\n" + ("\n" + h_rest if h_rest else "")
        return head + theirs
    return HUNK.sub(f, text)

files = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=U"], text=True).split()
for p in files:
    with open(p, newline="") as fh:
        s = fh.read()
    s2 = resolve(s, p)
    assert "<<<<<<<" not in s2 and ">>>>>>>" not in s2, p
    with open(p, "w", newline="") as fh:
        fh.write(s2)
    subprocess.check_call(["git", "add", p])
    print("resolved", p)
