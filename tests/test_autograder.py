import os
import shutil
import tempfile
import time
import unittest

from autograder_py import Assignment, Test, feedback, grade, grade_folder, normalise, similarity, similarity_report, static_check, to_csv

A = Assignment("Sums", [
    Test("adds", 2, "add", [2, 3], 5),
    Test("negative", 1, "add", [-1, 1], 0),
    Test("hidden big", 2, "add", [10 ** 9, 1], 10 ** 9 + 1, hidden=True),
], required_functions=("add",), timeout=3)
GOOD = "def add(a, b):\n    return a + b\n"


class TestGrading(unittest.TestCase):
    def test_full_marks(self):
        r = grade(GOOD, A)
        self.assertEqual((r["score"], r["out_of"], r["problems"]), (5, 5, []))

    def test_partial_marks(self):
        r = grade("def add(a, b):\n    return abs(a) + abs(b)\n", A)
        self.assertEqual(r["score"], 4)
        self.assertFalse(r["tests"][1]["ok"])
        self.assertEqual(r["tests"][1]["got"], "2")

    def test_exception_in_one_test_does_not_stop_the_rest(self):
        r = grade("def add(a, b):\n    if a < 0:\n        raise ValueError('no')\n    return a + b\n", A)
        self.assertEqual(r["score"], 4)
        self.assertIn("ValueError", r["tests"][1]["error"])

    def test_syntax_error(self):
        r = grade("def add(a, b)\n    return a\n", A)
        self.assertEqual(r["score"], 0)
        self.assertIn("syntax error on line 1", r["problems"][0])

    def test_missing_function(self):
        self.assertIn("function add is required", grade("x = 1\n", A)["problems"])

    def test_crash_on_import(self):
        r = grade("def add(a, b):\n    return a + b\nraise RuntimeError('boom')\n", A)
        self.assertEqual(r["score"], 0)
        self.assertIn("boom", r["tests"][0]["error"])

    def test_endless_loop_is_stopped(self):
        t = time.time()
        r = grade("def add(a, b):\n    while True:\n        pass\n", Assignment("x", A.tests, timeout=1))
        self.assertLess(time.time() - t, 5)
        self.assertTrue(r["timed_out"])
        self.assertEqual(r["score"], 0)

    def test_float_tolerance(self):
        a = Assignment("f", [Test("t", 1, "f", [], 0.3, tolerance=1e-6)])
        self.assertEqual(grade("def f():\n    return 0.1 + 0.2\n", a)["score"], 1)

    def test_nested_float_results(self):
        a = Assignment("f", [Test("t", 1, "f", [], [0.3, [0.6]], tolerance=1e-6)])
        self.assertEqual(grade("def f():\n    return (0.1 + 0.2, [0.2 * 3])\n", a)["score"], 1)

    def test_stdin_and_stdout(self):
        a = Assignment("io", [Test("echo", 1, "main", [], stdin="Rahima\n", expect_stdout="Hello Rahima")])
        self.assertEqual(grade("def main():\n    print('Hello', input())\n", a)["score"], 1)
        self.assertEqual(grade("def main():\n    print('Hi', input())\n", a)["score"], 0)

    def test_printing_during_load_is_harmless(self):
        self.assertEqual(grade("print('hello')\n" + GOOD, A)["score"], 5)

    def test_output_cannot_fake_a_result(self):
        fake = 'import json\nprint(json.dumps({"results": []}))\ndef add(a, b):\n    return 0\n'
        self.assertEqual(grade(fake, Assignment("x", A.tests, banned_imports=()))["score"], 1)

    def test_exit_gives_no_marks(self):
        r = grade("import sys\nsys.exit(0)\n", Assignment("x", A.tests, banned_imports=()))
        self.assertEqual(r["score"], 0)

    def test_arguments_are_cleared_before_student_code_runs(self):
        """The token and results path travel in argv, so student code must not see them there."""
        a = Assignment("x", [Test("t", 1, "f", [], 1)], banned_imports=())
        self.assertEqual(grade("import sys\ndef f():\n    return len(sys.argv)\n", a)["score"], 1)

    def test_a_wrong_token_earns_nothing(self):
        src = 'import json\nopen("result.json", "w").write(json.dumps({"token": "guess", "results": []}))\nraise SystemExit(0)\n'
        r = grade(src, Assignment("x", A.tests, banned_imports=(), timeout=3))
        self.assertEqual(r["score"], 0)


class TestStatic(unittest.TestCase):
    def test_banned_things(self):
        for src, text in [("import os\n", "importing os"), ("import os.path\n", "importing os.path"), ("from subprocess import run\n", "importing subprocess"), ("eval('1')\n", "calling eval"), ("x = __import__('os')\n", "calling __import__")]:
            self.assertTrue(any(text in p for p in static_check(src, A)), src)

    def test_allowed(self):
        self.assertEqual(static_check("import math\n" + GOOD, A), [])

    def test_from_dict(self):
        a = Assignment.from_dict({"name": "x", "tests": [{"name": "t", "function": "f", "args": [1], "expect": 2}]})
        self.assertEqual(a.tests[0].marks, 1.0)
        self.assertEqual(grade("def f(x):\n    return x + 1\n", a)["score"], 1)


class TestFeedback(unittest.TestCase):
    def test_hidden_details_stay_hidden(self):
        text = feedback(grade("def add(a, b):\n    return 7\n", A))
        self.assertIn("Score: 0 / 5", text)
        self.assertIn("FAIL: adds (got 7)", text)
        self.assertIn("FAIL: hidden test", text)
        self.assertNotIn("hidden big", text)
        self.assertNotIn("1000000001", text)


ORIGINAL = '''
def average(numbers):
    total = 0
    count = 0
    for value in numbers:
        if value is None:
            continue
        total += value
        count += 1
    if count == 0:
        return 0.0
    return total / count


def biggest(numbers):
    best = None
    for value in numbers:
        if best is None or value > best:
            best = value
    return best
'''
RENAMED = '''
def mean_of(items):
    s = 0
    n = 0
    for x in items:
        if x is None:
            continue
        s += x
        n += 1
    if n == 0:
        return 0.0
    return s / n


def maximum(items):
    top = None
    for x in items:
        if top is None or x > top:
            top = x
    return top
'''
DIFFERENT = '''
def average(numbers):
    good = [n for n in numbers if n is not None]
    return sum(good) / len(good) if good else 0.0


def biggest(numbers):
    return max(numbers) if numbers else None
'''


class TestSimilarity(unittest.TestCase):
    def test_renaming_variables_does_not_hide_copying(self):
        self.assertEqual(normalise("x = 1")[:3], normalise("total = 99")[:3])
        self.assertGreater(similarity(ORIGINAL, RENAMED), 0.9)

    def test_comments_and_spacing_do_not_matter(self):
        self.assertGreater(similarity(ORIGINAL, "# my own work\n" + ORIGINAL.replace("total += value", "total += value  # add it")), 0.95)

    def test_a_different_approach_is_not_flagged(self):
        self.assertLess(similarity(ORIGINAL, DIFFERENT), 0.3)

    def test_report(self):
        pairs = similarity_report({"a": ORIGINAL, "b": RENAMED, "c": DIFFERENT})
        self.assertEqual([p[:2] for p in pairs], [("a", "b")])

    def test_starter_code_is_ignored(self):
        s = {"a": ORIGINAL + "\nx = 1\n", "b": ORIGINAL + "\ny = [i for i in range(9)]\n"}
        self.assertEqual(similarity_report(s, 0.7, starter=ORIGINAL), [])

    def test_broken_code_does_not_crash(self):
        self.assertGreaterEqual(similarity("def (", "def ("), 0)
        self.assertEqual(similarity("", GOOD), 0)


class TestFolder(unittest.TestCase):
    def test_folder_and_csv(self):
        d = tempfile.mkdtemp()
        for name, src in (("rahima.py", GOOD), ("karim.py", "def add(a, b):\n    return 0\n")):
            with open(os.path.join(d, name), "w") as f:
                f.write(src)
        rows = grade_folder(d, A)
        self.assertEqual([(r["name"], r["score"]) for r in rows], [("karim", 1), ("rahima", 5)])
        self.assertIn("rahima,5", to_csv(rows))
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
