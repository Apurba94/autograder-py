"""Grade Python assignments: run tests in a separate process, and compare submissions.

Student code runs in a child process with a time limit, in an empty temporary folder, with
output captured. This protects against accidents, such as endless loops. It is NOT a security
sandbox: on a shared machine, grade inside a throwaway account, container or virtual machine.
"""
import ast
import csv
import hashlib
import io
import json
import keyword
import os
import secrets
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass, field

RUNNER = r'''
import builtins, contextlib, importlib.util, io, json, math, sys, traceback
token, code_path, spec_path, out_path = sys.argv[1:5]
sys.argv[:] = ["submission.py"]
with open(spec_path, encoding="utf-8") as f:
    tests = json.load(f)
results = []
real_open = builtins.open
sink = real_open(out_path, "w", encoding="utf-8")
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 ** 30, 2 ** 30))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
except (ImportError, ValueError, OSError):
    pass
def load():
    spec = importlib.util.spec_from_file_location("submission", code_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
def same(a, b, tol):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
        except TypeError:
            return False
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y, tol) for x, y in zip(a, b))
    return a == b
buffer = io.StringIO()
try:
    with contextlib.redirect_stdout(buffer):
        mod = load()
    loaded = True
    error = ""
except BaseException:
    loaded = False
    error = traceback.format_exc(limit=-2)
for t in tests:
    r = {"name": t["name"], "ok": False, "got": None, "error": ""}
    if not loaded:
        r["error"] = error
    else:
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                sys.stdin = io.StringIO(t.get("stdin", ""))
                got = None
                if t.get("function"):
                    fn = getattr(mod, t["function"], None)
                    if fn is None:
                        raise NameError("function " + t["function"] + " was not found")
                    got = fn(*t.get("args", []))
            if "expect_stdout" in t:
                text = out.getvalue().strip()
                r["ok"] = text == t["expect_stdout"].strip()
                r["got"] = text[:500]
            else:
                r["ok"] = same(got, t.get("expect"), t.get("tolerance", 1e-9))
                r["got"] = repr(got)[:500]
        except BaseException as exc:
            r["error"] = type(exc).__name__ + ": " + str(exc)[:300]
    results.append(r)
sink.write(json.dumps({"token": token, "results": results}))
sink.close()
'''


@dataclass
class Test:
    name: str
    marks: float = 1.0
    function: str = None
    args: list = field(default_factory=list)
    expect: object = None
    stdin: str = ""
    expect_stdout: str = None
    tolerance: float = 1e-9
    hidden: bool = False

    def spec(self):
        d = {"name": self.name, "function": self.function, "args": self.args, "expect": self.expect, "stdin": self.stdin, "tolerance": self.tolerance}
        if self.expect_stdout is not None:
            d["expect_stdout"] = self.expect_stdout
        return d


@dataclass
class Assignment:
    name: str
    tests: list
    banned_imports: tuple = ("os", "subprocess", "socket", "shutil", "ctypes", "pathlib")
    banned_calls: tuple = ("exec", "eval", "compile", "__import__")
    required_functions: tuple = ()
    timeout: float = 5.0

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], [Test(**t) for t in d["tests"]], tuple(d.get("banned_imports", cls.banned_imports)), tuple(d.get("banned_calls", cls.banned_calls)), tuple(d.get("required_functions", ())), d.get("timeout", 5.0))


def static_check(source, a):
    """Rules read from the code without running it. Returns a list of problems."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}: {exc.msg}"]
    problems = []
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.split(".")[0] in a.banned_imports:
                    problems.append(f"line {node.lineno}: importing {n.name} is not allowed here")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in a.banned_imports:
                problems.append(f"line {node.lineno}: importing {node.module} is not allowed here")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in a.banned_calls:
            problems.append(f"line {node.lineno}: calling {node.func.id} is not allowed here")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
    for name in a.required_functions:
        if name not in defined:
            problems.append(f"function {name} is required")
    return problems


def grade(source, assignment):
    """Grade one submission. Returns {"score", "out_of", "tests", "problems", "timed_out"}."""
    out_of = sum(t.marks for t in assignment.tests)
    problems = static_check(source, assignment)
    if problems:
        return {"score": 0.0, "out_of": out_of, "tests": [], "problems": problems, "timed_out": False}
    with tempfile.TemporaryDirectory() as d:
        code = os.path.join(d, "submission.py")
        spec = os.path.join(d, "spec.json")
        out = os.path.join(d, "result.json")
        run = os.path.join(d, "runner.py")
        with open(code, "w", encoding="utf-8") as f:
            f.write(source)
        with open(spec, "w", encoding="utf-8") as f:
            json.dump([t.spec() for t in assignment.tests], f)
        with open(run, "w", encoding="utf-8") as f:
            f.write(RUNNER)
        token = secrets.token_hex(16)        # stops casual forgery; code in this process could still dig it out
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        timed_out = False
        crashed = ""
        try:
            p = subprocess.run([sys.executable, "-I", run, token, code, spec, out], cwd=d, env=env, capture_output=True, timeout=assignment.timeout, stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                crashed = p.stderr.decode("utf-8", "replace")[-300:]
        except subprocess.TimeoutExpired:
            timed_out = True
        data = None
        if os.path.exists(out):
            try:
                with open(out, encoding="utf-8") as f:
                    data = json.load(f)
            except ValueError:
                data = None
        if data is None or data.get("token") != token:
            note = f"stopped after {assignment.timeout:g} seconds" if timed_out else f"the program ended before its tests finished {crashed}".strip()
            return {"score": 0.0, "out_of": out_of, "tests": [], "problems": [note], "timed_out": timed_out}
    rows = []
    score = 0.0
    by_name = {t.name: t for t in assignment.tests}
    for r in data["results"]:
        t = by_name[r["name"]]
        earned = t.marks if r["ok"] else 0.0
        score += earned
        rows.append({**r, "marks": t.marks, "earned": earned, "hidden": t.hidden})
    return {"score": score, "out_of": out_of, "tests": rows, "problems": [], "timed_out": False}


def feedback(result):
    """Text safe to give a learner: hidden tests show only pass or fail."""
    lines = [f"Score: {result['score']:g} / {result['out_of']:g}"]
    lines += [f"Problem: {p}" for p in result["problems"]]
    for t in result["tests"]:
        mark = "pass" if t["ok"] else "FAIL"
        if t["hidden"]:
            lines.append(f"{mark}: hidden test")
        else:
            detail = "" if t["ok"] else f" (got {t['got']}{', ' + t['error'] if t['error'] else ''})"
            lines.append(f"{mark}: {t['name']}{detail}")
    return "\n".join(lines)


def normalise(source):
    """Turn code into a token stream with names and strings removed, so renaming variables changes nothing."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NAME:
                out.append(tok.string if keyword.iskeyword(tok.string) else "N")
            elif tok.type == tokenize.NUMBER:
                out.append("0")
            elif tok.type == tokenize.STRING:
                out.append("S")
            elif tok.type == tokenize.OP:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        out = source.split()
    return out


def fingerprints(source, k=12, window=8):
    """Winnowing (Schleimer et al. 2003), the method behind MOSS: keep the smallest hash of each window."""
    toks = normalise(source)
    if len(toks) < k:
        return {hashlib.md5(" ".join(toks).encode()).hexdigest()} if toks else set()
    hashes = [hashlib.md5(" ".join(toks[i:i + k]).encode()).hexdigest() for i in range(len(toks) - k + 1)]
    if len(hashes) <= window:
        return {min(hashes)}
    return {min(hashes[i:i + window]) for i in range(len(hashes) - window + 1)}


def similarity(a, b):
    fa, fb = fingerprints(a), fingerprints(b)
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / min(len(fa), len(fb))


def similarity_report(submissions, threshold=0.7, starter=None):
    """submissions: {name: source}. Returns pairs to look at, highest first. Starter code is not counted."""
    base = fingerprints(starter) if starter else set()
    prints = {k: fingerprints(v) - base for k, v in submissions.items()}
    names = sorted(prints)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if prints[a] and prints[b]:
                s = len(prints[a] & prints[b]) / min(len(prints[a]), len(prints[b]))
                if s >= threshold:
                    out.append((a, b, s))
    return sorted(out, key=lambda t: -t[2])


def grade_folder(folder, assignment):
    """Grade every .py file in a folder. Returns rows sorted by name."""
    rows = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                r = grade(f.read(), assignment)
            rows.append({"name": name[:-3], "score": r["score"], "out_of": r["out_of"], "notes": "; ".join(r["problems"])})
    return rows


def to_csv(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, ["name", "score", "out_of", "notes"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()
