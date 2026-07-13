# T-9.3 — examples/demo.py end-to-end

## Files

- `tests/test_demo.py` (new) — 3 subprocess-based tests.

## Tests

1. `test_demo_exits_cleanly` — asserts `python examples/demo.py` exits 0.
2. `test_demo_output_mentions_v0_1` — asserts the `tinydb v0.1 demo`
   banner appears in stdout.
3. `test_demo_runs_all_ten_steps` — asserts each of the 10 step
   banners (`step 2` … `step 10`) appears in stdout.

## Verification

```
$ python -m pytest tests/test_demo.py -v
tests/test_demo.py::test_demo_exits_cleanly PASSED                       [ 33%]
tests/test_demo.py::test_demo_output_mentions_v0_1 PASSED                [ 66%]
tests/test_demo.py::test_demo_runs_all_ten_steps PASSED                  [100%]
3 passed in 1.52s

$ python -m pytest tests/ --cov=src/tinydb --cov-fail-under=80 -q
TOTAL                                  3670    277    92%
Required test coverage of 80% reached. Total coverage: 92.45%
817 passed in 29.67s
```

## Deviations

- Brief suggested one test that checked `returncode == 0` and one
  substring assertion.  Added a third test that confirms all 10 step
  banners appear in stdout — the brief itself lists 10 steps so this
  is a tight fit.
- Did not use `pytest.mark.timeout` (the plugin is not installed;
  used `subprocess.run(timeout=30)` instead, which gives equivalent
  protection without an extra dependency).

## Commit

- `5047d79` — test: T-9.3 examples/demo.py subprocess smoke test