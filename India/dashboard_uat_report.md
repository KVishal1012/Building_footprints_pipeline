# Dashboard QA/UAT Report

Target: `http://localhost:8501`

Branch: `test`

Dashboard commit: `9dc6114b Clarify dashboard baseline review UX`

Run time: 2026-04-26 21:53 EDT / 2026-04-27T01:53Z

## QA Results

- [x] Dashboard unit tests passed: `.venv/bin/python -B -m unittest India.tests.test_urban_growth_dashboard`
- [x] Compile check passed: `.venv/bin/python -B -m py_compile India/urban_growth_dashboard.py India/tests/test_urban_growth_dashboard.py`
- [x] Metrics sanity check passed for Chennai and Bengaluru.

| City | Layer rows | Scenarios | Sources | Link rows | Linked structures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bengaluru | 14,710 | 6 | 6 | 3,035 | 1,142 |
| Chennai | 7,722 | 6 | 6 | 1,852 | 727 |

## Browser UAT Results

- [x] Page reload shows title `Urban Scenario Review`.
- [x] Header shows `Urban Scenario Review Dashboard`.
- [x] Copy states current outputs are heuristic baselines, not deep-learning predictions.
- [x] Sidebar action is `Apply Review Filters`, not `Run Simulation`.
- [x] Prediction Method panel is visible with `Heuristic baseline` active and `No AI model loaded`.
- [x] City readiness panel is visible and lists both Bengaluru and Chennai.
- [x] City selector exposes `All cities`, `Bengaluru`, and `Chennai`.
- [x] Bengaluru filter updates the dashboard to 14,710 layer rows and 1,142 linked structures.
- [x] Bengaluru filter removes Chennai scenario rows from the visible output stack.
- [x] SourceName display mode updates the map panel to `SourceName Baseline Indicator Map`.
- [x] Sources, Links, and Metrics tabs render with Bengaluru context.

Note: Browser UAT used DOM assertions through the in-app browser. Screenshot capture timed out through CDP, so visual verification evidence is text/DOM based.
