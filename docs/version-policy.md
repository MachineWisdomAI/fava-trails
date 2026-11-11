# Repository version policy

The updater needs Python 3.11 or newer and no third-party libraries. Select that
interpreter explicitly if the system `python3` is older (for example,
`python3.13 scripts/mw-version.py ...` on macOS).

Bump affected product versions in the original change PR. Documentation,
tests, CI, repository metadata, and development checks alone do not need a bump.
The updater determines this from changed paths, not the PR title; a mixed PR
still bumps the affected product. Run it before review and after updating from main:

```bash
git fetch origin main
python3 scripts/mw-version.py update --base origin/main --title 'chore(deps): update transitive dependency'
python3 scripts/mw-version.py check --base origin/main --title 'chore(deps): update transitive dependency'
```

Use the actual PR title. Supply `--body-file PATH` for its body, or `--event-file`
with a GitHub pull-request event containing title/body. The updater also reads
the PR branch's commits. One PR gets the largest applicable increment: features
are minor; fixes and other product changes, including runtime dependencies,
are patch. `!`, `BREAKING CHANGE:`, or
`BREAKING-CHANGE:` is major from 1.0 onward and minor before 1.0. A dependency's
own major number does not establish a breaking change in this project.

`.version-policy.json` lists version units, paths, and synchronized files. Changes
outside all unit paths affect every unit, except configured `exclude_paths`.
The standard non-release paths cover Markdown/reStructuredText, `docs/`, test
directories and test files, `.github/`, Git/editor metadata, and repository
version/test/check scripts. Other paths conservatively count as product changes.
Use optional `release_paths` glob patterns for files that ship as product despite
those defaults, such as `skills/**`, `skillsets/**`, or `src/content/**`. Review
the actual package/build inputs when adopting the policy: installed skills,
runtime prompts, templates, and rendered site content are product, even in
Markdown. Existing `exclude_paths` still exclude captured or vendored material.
Existing `release_paths` cannot be removed or narrowed in a change PR.
Root units use `**`. Lockfiles retain their resolved dependencies. Updating again
uses the base version, so it does not accumulate bumps. Update your branch from
current main before merging; the required check rejects a stale base.

Prereleases advance the base and reset the counter: `0.1.0-rc.5` becomes
`0.1.1-rc.1` for a patch. Python metadata serializes the same version as
`0.1.1rc1`. Date prereleases retain that format and refresh the date; `--date`
accepts YYYY-MM-DD for reproducible runs. CI accepts a valid date between the
previous version's date and today, so an overnight review does not invalidate it.

Explicit release promotion uses the exact title `chore(release): promote version`
and changes only configured version values: `0.1.1-rc.1` becomes `0.1.1`, without
another base increment. Existing release review and publication authority still
apply. The updater never creates a tag, release, publication, or deployment.

A stable baseline enters the release-candidate channel only when the PR body has
a line exactly `Release-Channel: rc`: `0.8.3` becomes `0.8.4-rc.1` (`0.8.4rc1`
in Python metadata) for a patch, using the normal largest-increment rule. The
marker is rejected on a baseline that is already a prerelease, which keeps its
channel (`0.8.4-rc.1` becomes `0.8.5-rc.1`) and is promoted only by the exact
promotion title above. Release tags must equal `v` plus the PEP 440 package
version (`v0.8.4rc1`, `v0.8.4`); the Release workflow rejects any mismatch.

A stable baseline whose product change already carries its bump (so it was
merged but never published) enters the candidate channel without a second
increment only when the PR body has a line exactly `Release-Channel: rc-same-base`:
`0.9.3` becomes `0.9.3-rc.1` (`0.9.3rc1` in Python metadata). The case is
metadata-only: after stripping the configured version values, every changed path
must be a non-release path (documentation, tests, CI, version scripts); any
remaining product difference from the base is rejected. It needs a stable
baseline, is mutually exclusive with `Release-Channel: rc`, is ignored by the
promotion title, and never writes a tag, release, or publication. Tag the merged
main tip as `v0.9.3rc1`; the same version is later promoted by the exact
promotion title (`0.9.3rc1` becomes `0.9.3`) with no base increment.

To prove the candidate artifacts, run
`python3 scripts/check-rc-artifact-identity.py --base-ref REF`. It builds the base
commit and the candidate with `uv build` and fails unless the wheel and sdist
differ only in version metadata and renamed files.

For a new versioned component, run the toolkit bootstrap again or run
`python3 scripts/mw-version.py enroll --repo PATH --unit COMPONENT_PATH` from an
installed copy. Review the generated configuration and add any runtime/plugin
mirrors. Captured templates and vendored packages are not owned version units.
