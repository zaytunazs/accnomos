"""One-off: resolve the two 'both added' conflicts between claude/ask-books and claude/mail-intake."""
import re, sys

def keep_both(s):
    return re.sub(r"<<<<<<< HEAD\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", lambda m: m.group(1) + m.group(2), s, flags=re.S)

def resolve_ts(s):
    def f(m):
        head, theirs = m.group(1), m.group(2)
        h_member, h_rest = head.split("};\n", 1)
        t_member, t_rest = theirs.split("};\n", 1)
        return h_member + t_member + "};\n" + h_rest + "}\n\n" + t_rest
    return re.sub(r"<<<<<<< HEAD\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", f, s, flags=re.S)

main_py, runtime_ts = sys.argv[1], sys.argv[2]
for path, fn in ((main_py, keep_both), (runtime_ts, resolve_ts)):
    with open(path, newline="") as fh:
        s = fh.read()
    s2 = fn(s)
    assert "<<<<<<<" not in s2 and ">>>>>>>" not in s2, path
    with open(path, "w", newline="") as fh:
        fh.write(s2)
print("resolved")
