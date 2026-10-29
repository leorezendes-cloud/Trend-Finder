# Preserve functionality while reclaiming archival disk space

No larger disk is required to try this repair. The maintenance command shares
physical disk blocks for byte-identical immutable archives. Original files stay
at their original names, with exactly the same bytes and SHA-256 values. They
remain regular files: no compressed format, symlinks, archive extraction, reader
migration, loss of evidence, or dependency on a running personal computer.

## What changes

- Completed atomic forecast staging snapshots, old input snapshots, captured
  HTML/JSON, and old statistics/personnel snapshots can share identical bytes.
  Checksums are used to find candidates, followed by a full streaming byte
  comparison before the atomic exchange. Different permissions/owners/devices
  do not share a file. Only archives at least one hour old are eligible.
- New primary and backup raw captures keep each observation's original filename
  and independently captured timestamp/manifest, while identical response bodies
  share storage immediately. Saved market rows and freshness rules are unchanged.
- Existing issued Scout forecasts, ATS/O-U receipts, dynamic journals/closing
  receipts, live CSVs, account data and incomplete recovery attempts are excluded.
- The full updater tries maintenance before checking its unchanged 128 MiB free
  space guard. Maintenance is daily when space is healthy and retried when low.
- When every eligible future game already has a valid sealed forecast, the
  updater validates the configured code and existing seals, then avoids another
  full isolated snapshot/model run. Missing games still use the unchanged engine;
  interrupted work still recovers first. Finals, statistics, market refreshes,
  dynamic selections, receipt publication and grading continue normally.

These are immutable archives; supported code never edits them in place. Physical
sharing can change filesystem link counts and modification times. Acquisition
and pregame timestamps inside the untouched manifests/receipts remain the source
of truth. No filenames or historical record contents are changed or removed.

## Apply on Render after deploying

```sh
python -m storage_maintenance --apply
```

The default root is `/var/data/site-data`. The report includes `reclaimed_mib`
and `free_after_mib`. Without `--apply`, the command only estimates savings.
Both modes take the normal updater/capture locks; retry after an active worker
finishes if the command reports busy. `df -h /var/data` shows actual free space.

If the report shows sufficient space, resume production verification:

```sh
TREND_FINDAH_EXPERT_AUTO_DRAFT=0 TREND_FINDAH_CONTEXT_RESEARCH=0 python hosted_updates.py --once
python -m plug_dynamic_readiness --activate
```

The existing restart-checkpoint and unattended-market-tick requirements still
apply. Keep `TREND_FINDAH_DYNAMIC_OFFICIAL=0` until activation succeeds. If duplicate
archives cannot reclaim enough space, the 128 MiB guard continues to pause full
updates. The command does not erase unique evidence to force an update through.
Actual Render savings must be measured there; local test results are not a claim
about the hosted volume. Unique archival data can still grow over time.

## Validation

192 tests pass in the workflow and memory/feed suites. Coverage includes
byte-for-byte preservation at all original paths, manifest hash bindings,
independent primary/backup observation timestamps, idempotent cleanup, corrupt
pool rejection, no writes through symlinks, interrupted links, exclusion of
live/immutable issued records and recoverable staging, completed staging hash
verification, unchanged model output, kickoff locks, graders and repeat updates
without redundant snapshots. Hashing/comparison uses 256 KiB chunks.
