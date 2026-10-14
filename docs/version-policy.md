# Repository version policy

The updater needs Python 3.11 or newer and no third-party libraries. Select that
interpreter explicitly if the system `python3` is older (for example,
`python3.13 scripts/mw-version.py ...` on macOS).

Every change PR updates affected versions before merge. Run the repository-local
updater after your implementation and again after updating the branch from main:

```bash
git fetch origin main
python3 scripts/mw-version.py update --base origin/main --title 'chore(deps): update transitive dependency'
python3 scripts/mw-version.py check --base origin/main --title 'chore(deps): update transitive dependency'
```

Use the actual PR title. Supply `--body-file PATH` for its body, or `--event-file`
with a GitHub pull-request event containing title/body. The updater also reads
the PR branch's commits. One PR gets the largest applicable increment: features
are minor; fixes and every other change (including chores, docs, tests, CI, and
direct/transitive dependencies) are patch. `!`, `BREAKING CHANGE:`, or
`BREAKING-CHANGE:` is major from 1.0 onward and minor before 1.0. A dependency's
own major number does not establish a breaking change in this project.

`.version-policy.json` lists version units, paths, and synchronized files. Changes
outside all unit paths affect every unit, except configured `exclude_paths`.
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

For a new versioned component, run the toolkit bootstrap again or run
`python3 scripts/mw-version.py enroll --repo PATH --unit COMPONENT_PATH` from an
installed copy. Review the generated configuration and add any runtime/plugin
mirrors. Captured templates and vendored packages are not owned version units.
