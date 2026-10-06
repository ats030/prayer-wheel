# Google Cloud cleanup, 2026-10-06

Issue: `ats030-frnlm`. The user requested keeping six specified Cloud Run
services and deleting the other services to reduce recurring charges.

## Retained services

All six are in `ikimono-note-12205`: `dekita-app`, `ikimono-note`,
`omatsuri-map`, `onsen-map`, `shiseki-map`, and `tokusan-map`.
The user's six URLs returned HTTP 200 after cleanup.

## Deleted resources

- Cloud Run: `cloud-cost` and `history-timeline` in `ikimono-note-12205`;
  `dekita` and `dekita-app` in `dekita-507214`.
- Artifact Registry: the `cloud-cost` and `history-timeline` packages in
  `ikimono-note-12205/cloud-run-source-deploy`; all three image repositories
  in `dekita-507214` (`cloud-run-source-deploy`, `dekita`, and `gcr.io`).
- Cloud Storage: the two removed services' source prefixes in
  `run-sources-ikimono-note-12205-asia-northeast1`; the deployment-only buckets
  `dekita-507214_cloudbuild` and `run-sources-dekita-507214-asia-northeast1`.
- Secret Manager: 395 old versions destroyed, leaving seven enabled versions,
  one latest version per secret. All revisions of the retained services were
  inspected: their Secret references use `latest`, with no pinned old versions.
  Secret values were not retrieved.

Application data, shared resources of retained services, billing export data,
and local application source were retained. No projects were deleted.

## Verification and cost limits

Cloud Run lists exactly the six retained services in `ikimono-note-12205` and
none in `dekita-507214`. The latter project has no Artifact Registry repositories
or Cloud Storage buckets. The removed image packages are absent. Secret version
metadata confirms seven enabled and 395 destroyed versions. All six user URLs
returned HTTP 200; authenticated application workflows were not exercised.

The billing export previously showed JPY 478.9694 for Secret version storage
in invoice month 202610. This is already accrued usage, not a monthly forecast.
Destroyed versions no longer accrue storage charges; disabled versions would.
Seven retained versions exceed the six-version free allowance by one, assuming
no other usage against the same billing account. Network and storage charges
for retained services can continue. Actual post-cleanup charges have not yet
been reconciled against a later billing export.

Google pricing reference: https://cloud.google.com/secret-manager/pricing

The deployment scripts still add a Secret version each time they deploy.
Recurrence prevention is tracked separately in `ats030-0ghlc`.
Destroyed Secret versions are not recoverable; removed services can be rebuilt
from local source if required.
