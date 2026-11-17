---
name: amagi-trace
description: Turn a failed Playwright run (a trace.zip or the whole test-results/ folder) into one markdown file per failed test, with the step list, failing locator and assertion, test source around the failing line, console errors, uncaught page errors, failed network calls, the page's DOM text at the moment of failure and a screenshot. Use when the user asks to fix, debug or explain a failing or flaky Playwright E2E test, a red CI run, or hands over a trace.zip or test-results folder, so you can see what the page looked like instead of guessing from the stack trace.
---

# amagi-trace

A CLI that reads Playwright traces (`trace.zip`, or any folder that contains them, such as
`test-results/`) and writes one markdown file per
failed test. The files are meant for you to read instead of opening the trace viewer.

## When to use this skill

- A Playwright test is red locally or in CI and you have `test-results/` or a `trace.zip`
  (download the CI artifact first if needed).
- The stack trace says "Timeout" or "expected X received Y" and you need to know what the page
  actually showed, which requests failed and what the console said.
- Before changing a locator: check the DOM text section to see whether the element exists,
  is hidden, or has different text than the test expects.

Do not use it for tests that never ran a browser, or when no trace was recorded. Tell the user to
set `trace: 'retain-on-failure'` (or `'on-first-retry'`) in `playwright.config`.

## How to use it

Install once: `pipx install amagi-trace`, or from source with
`pipx install git+https://github.com/amagilabs/amagi-trace` (or `pip install -e .` from this repo).

```bash
amagi-trace test-results/                  # writes ./trace-md/index.md + one .md per failed test
amagi-trace path/to/trace.zip --stdout     # print one trace's report, write nothing
amagi-trace test-results/ -o out --all     # include passing tests too
amagi-trace test-results/ --source-dir .   # trace came from CI: read specs from this folder
```

Read `trace-md/index.md` first (one line per failure with the first error line), then open the
file for the test you are fixing. Open the screenshot file it links to if you can view images.

Useful options: `--max-dom N` (DOM text lines, default 80), `--all-console` (every console
message, not just errors and warnings), `--hooks` (show fixture and hook steps),
`--no-screenshots`.

## Reading the result

- **Failure**: the runner's error with ANSI colour removed, including Playwright's call log.
- **Failing step**: the step title, the locator as written in the test, the internal selector and
  the line in the spec. **Test source** shows the lines around it.
- **Steps**: every user-level step with `[ok]` or `[FAIL]` and its duration; the steps that ran
  after the failure (After Hooks) are hidden.
- **Console and page errors**: console errors and warnings plus uncaught exceptions
  (`[pageerror]`), repeated lines folded with a count, times relative to the start of the test.
- **Failed network calls**: HTTP 4xx/5xx and requests with no response, with the request body
  and the first 300 characters of a text response body.
- **Page at the moment of failure**: the DOM text from the snapshot taken at the failing step.
  `<-- TARGET` marks the element the action or assertion was aimed at. Hidden elements are
  skipped, input values are shown.
- **ARIA snapshot**: Playwright's own `error-context.md`, when it sits next to the trace.

## Limits

- Only the main frame's DOM is shown; iframe content is not rendered.
- DOM text is a readable outline, not full HTML. If you need an attribute that is not shown,
  say so; the trace itself still has it.
- Traces recorded without `snapshots: true` have no DOM section.
- The tool never runs the tests or the browser and never uploads anything.
