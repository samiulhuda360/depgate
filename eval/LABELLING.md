# Labelling guide

This guide defines the correct answer for every question depgate asks about a dependency-update pull request.
Every item in `eval/data/labels.jsonl` was labelled by these rules.

## What one item contains

| Field | Where it comes from |
|---|---|
| Package, ecosystem, old and new version, semver jump | A real release pair of a public npm or PyPI package |
| Release notes | The package's public GitHub release notes for every release after the old version, up to and including the new one |
| Advisories | GitHub Advisory Database entries that affect the old version and not the new one |
| CI status | Simulated: 80% `success`, 12% `failure`, 8% `pending` (fixed seed) |
| Repository files | One or two short, invented source files that use the package, as the consuming repository would |

The repository files are invented on purpose. Each one is written for its release notes: for about half of the
updates whose notes describe a breaking change, the files use an API, option or runtime that the breaking change
touches, and for the other half they only use parts that did not change. That is what makes "does the breaking
change affect this repository?" a real question rather than a copy of "is there a breaking change?".

## The five yes/no questions

**`breaking_in_notes`: the release notes describe a breaking change.**
Yes when the notes say, in words, that existing users may have to change code, config or environment. Typical
signals: a "Breaking changes" heading; "removed", "dropped", "renamed", "no longer", "now throws" or "default
changed" about public behaviour; a migration guide; dropping a supported Node or Python version.
No when the notes only list fixes, features, deprecations (a warning, not a removal), docs, or internal changes.
A major version number on its own is not enough: if the notes do not describe what breaks, the answer is no.

**`breaking_affects_repo`: a breaking change affects APIs this repository uses.**
Yes only when `breaking_in_notes` is yes and the repository files use something the breaking change touches: a
removed or renamed function, a changed option or default the code relies on, a changed return type it reads, or a
runtime version the repository still declares (for example `"engines": {"node": ">=16"}` when Node 16 is dropped).
Otherwise no.

**`security_fix`: the update fixes a security vulnerability.**
Yes when at least one advisory is listed, or the notes explicitly describe a security fix (a CVE or GHSA id,
"security", "vulnerability", ReDoS, prototype pollution, request smuggling, path traversal and so on). A fix to a
crash or a wrong result with no security framing is no.

**`runtime_change`: the update changes runtime or engine requirements.**
Yes when the notes raise a minimum or drop support for a Node, Python, browser or engine version, or add a new
required runtime or peer dependency. Adding support for a newer runtime, while keeping the old ones, is no.

## Upgrade risk (score 0 to 3)

| Level | Meaning | Typical case |
|---|---|---|
| 0 | Trivial | A patch with bug fixes, docs or internal changes only; CI green |
| 1 | Low | New features, behaviour fixes or deprecations, no breaking change; or a security fix with no breaking change; CI green |
| 2 | Medium | A breaking change that does not touch this repository; a runtime requirement change; a major bump whose notes say nothing useful; CI still running |
| 3 | High | A breaking change that touches this repository, or CI failing |

When two rows apply, the higher level wins.

## Decision (choice)

| Decision | Rule |
|---|---|
| `hold` | CI is failing, or `breaking_affects_repo` is yes. Do not merge until someone changes the code. |
| `merge_after_review` | Otherwise, when risk is 2: a person should read the notes first. |
| `auto_merge` | Otherwise (risk 0 or 1 and CI green). Safe to merge without a person. |

A security fix does not change the decision by itself; the policy gives it a priority label instead.

## Worked examples

| Update | Notes say | Repository uses | Labels |
|---|---|---|---|
| patch, CI green | "Fix memory leak in stream parser" | the parser | not breaking, risk 0, `auto_merge` |
| minor, CI green | "Add `timeout` option; deprecate `legacyMode`" | `legacyMode` | not breaking (deprecation only), risk 1, `auto_merge` |
| major, CI green | "Drop Node 14; remove `callback` API" | promises only, engines `>=18` | breaking, not affecting, runtime change, risk 2, `merge_after_review` |
| major, CI green | "Remove `callback` API" | `client.get(url, cb)` | breaking, affecting, risk 3, `hold` |
| patch, CI failing | "Fix typo in error message" | anything | not breaking, risk 3, `hold` |
| patch, CI green, advisory listed | "Fix ReDoS in header parsing" | anything | security fix, risk 1, `auto_merge` (with a priority label) |
