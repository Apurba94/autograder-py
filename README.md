# AutoGrader

Grade a class's Python assignments in seconds. It gives partial marks, keeps hidden tests hidden, gives learners useful feedback, and points out pairs of submissions worth a second look.

`assignment.json`:

```json
{
  "name": "Week 3",
  "required_functions": ["add"],
  "timeout": 5,
  "tests": [
    {"name": "adds two numbers", "marks": 2, "function": "add", "args": [2, 3], "expect": 5},
    {"name": "large values", "marks": 3, "function": "add", "args": [1000000000, 1], "expect": 1000000001, "hidden": true},
    {"name": "greets", "marks": 1, "function": "main", "stdin": "Rahima\n", "expect_stdout": "Hello Rahima"}
  ]
}
```

```
python -m autograder_py assignment.json submissions/ results.csv
```

## What it checks

- **Behaviour:** function results, with a tolerance for floats, and printed output for given input
- **Rules:** banned imports and calls, and required functions, read from the code without running it
- **Marks:** each test has its own marks, and one crash does not stop the other tests

## Feedback for learners

`feedback(result)` shows what failed and what the program returned, and hidden tests show only pass or fail, so their inputs stay secret.

## Similarity

Comparison uses winnowing, the method behind MOSS. Code is first reduced to its structure, so renaming variables or adding comments does not hide copying, and any starter code you give is ignored.

Similarity is a reason to talk to learners, never proof. Short exercises often have few natural solutions, so please look at the code and ask before deciding anything.

## Safety: please read

Each submission runs in a separate process, in an empty temporary folder, with a time limit, a reduced environment and, on Linux, a memory limit. This stops accidents such as endless loops, and a random token stops a program from faking a result by printing it or writing a file.

**It is not a security sandbox, and it does not stop a determined cheat.** Student code runs in the same process as the test runner, so a skilled student could reach the token in memory and forge full marks. The banned-import check can be bypassed too, and on Windows there is no memory limit. Treat grades as a first pass, read the code of any surprising result, and on a machine that matters run the grader inside a container, a virtual machine or a throwaway account with no access to your files.

## How it is tested

Tests run real submissions: endless loops, crashes on import, programs that exit early, and simple attempts to forge results. Similarity tests confirm that renamed copies score above 90%, while a different approach scores below 30%.

## Tests

```
python -m unittest discover -s tests
```

MIT licence.
