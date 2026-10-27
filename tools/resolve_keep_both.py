"""Resolve 'both added' conflict hunks by keeping HEAD then THEIRS, in every conflicted file git reports.

Usage: python tools/resolve_keep_both.py [--table-first]
Safe only for additive conflicts (new rows, imports, routers, cards). Prints the files it touched; refuses hunks where both sides
modify the same line (same first line) so a human can look.
"""

import re
import subprocess

HUNK = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)


def resolve(text: str, path: str) -> str:
    def f(m):
        head, theirs = m.group(1), m.group(2)
        h1 = head.strip().splitlines()[:1]
        t1 = theirs.strip().splitlines()[:1]
        if h1 and t1 and h1 == t1:
            raise SystemExit(f"{path}: both sides change the same line; resolve by hand")
        # README: keep HEAD's block, and add only THEIRS' table rows whose first cell is new (never duplicate rows,
        # never let a prose block split a table).
        if path.endswith("README.md"):

            def key(row: str) -> str:
                cells = [c.strip() for c in row.split("|")]
                return (
                    (cells[2] if row.startswith("| 2") and len(cells) > 2 else cells[1])[:60] if len(cells) > 1 else row
                )

            have = {key(r) for r in head.splitlines() if r.startswith("|")}
            new_rows = [
                r for r in theirs.splitlines() if r.startswith("|") and not r.startswith("|---") and key(r) not in have
            ]
            h_rows, _, h_rest = head.partition("\n\n")
            if h_rows.lstrip().startswith("|"):
                return (
                    h_rows.rstrip("\n") + "\n" + "".join(r + "\n" for r in new_rows) + ("\n" + h_rest if h_rest else "")
                )
            return head + "".join(r + "\n" for r in new_rows)
        if path.endswith((".ts", ".tsx")):
            # Both sides appended members to the same `runtime = {...}` object: merge inside one closing `};`.
            closer = re.compile(r"\n};?\n")
            if closer.search(head) and closer.search(theirs):
                hm, hr = closer.split(head, 1)
                tm, tr = closer.split(theirs, 1)
                return hm + "\n" + tm + "\n};\n" + hr + tr
            # Git's common-suffix trimming can swallow a `}` that closes HEAD's last interface: put it back when HEAD's
            # last line is still inside a block and THEIRS starts a new top-level declaration.
            hl = head.rstrip("\n").splitlines()
            if (
                hl
                and hl[-1].startswith("  ")
                and re.match(r"(/\*\*|export |interface |type |const |function )", theirs.lstrip())
            ):
                return head.rstrip("\n") + "\n}\n\n" + theirs
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
