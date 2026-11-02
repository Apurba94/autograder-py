"""Grade a folder of .py files: python -m autograder_py assignment.json submissions/ [results.csv]"""
import json
import os
import sys

from . import Assignment, grade_folder, similarity_report, to_csv


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        a = Assignment.from_dict(json.load(f))
    rows = grade_folder(argv[2], a)
    text = to_csv(rows)
    if len(argv) > 3:
        with open(argv[3], "w", encoding="utf-8", newline="") as f:
            f.write(text)
    print(text)
    sources = {}
    for name in os.listdir(argv[2]):
        if name.endswith(".py"):
            with open(os.path.join(argv[2], name), encoding="utf-8", errors="replace") as f:
                sources[name] = f.read()
    pairs = similarity_report(sources)
    if pairs:
        print("Pairs to look at (similar structure does not prove copying):")
        for a_name, b_name, s in pairs:
            print(f"  {s:.0%}  {a_name}  {b_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
