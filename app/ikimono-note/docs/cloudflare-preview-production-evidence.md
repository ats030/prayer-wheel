# Protected preview: production evidence

Observed on 2026-10-08 for `ikimono-note-preview`, deployed version
`402d1c1d-c449-4c4a-a4ac-809f3f91d653`. Migration issue: `ats030-paskw`.

## Login and Drive

The user reported successful Google login, Drive authorization, and saving a
photo record in the preview followed by reading the photo and record back in a
different browser using the same Google account. This is a user-reported manual
check, rather than an automated browser trace.

A read-only remote D1 query returned `user_count = 1`, `rows_written = 0`,
`changed_db = false`, and database size `40960` bytes:

```sql
SELECT COUNT(*) AS user_count FROM users;
```

No user identities, original records, or old shared photos were read for this check.
These observations do not establish complete migration of old records or shares.

## CPU accounting

Cloudflare GraphQL query window: `2026-10-08T13:52:00Z` through
`2026-10-08T14:16:13Z`, filtered to `ikimono-note-preview`.

| Invocation status | Requests | Reported errors | Subrequests | CPU P50 | CPU P99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| success | 503 | 0 | 31 | 15.186 ms | 409.160 ms |
| clientDisconnected | 11 | 0 | 7 | 9.797 ms | 24.302 ms |

The GraphQL schema describes `cpuTimeP50` and `cpuTimeP99` as microseconds.
The raw values were respectively `15186`/`409160` and `9797`/`24302`; the table
divides them by 1000. This is production analytics, unlike earlier local active
sampling. It aggregates all matching requests and cannot attribute CPU cost to
login, static assets, identification, or shared-photo storage. Startup cost and
individual request characteristics were not separated. No external AI quality
claim follows from this result.

The [Workers Free CPU limit](https://developers.cloudflare.com/workers/platform/limits/)
is 10 ms per invocation. The observed successful-request quantiles exceed that
number, even though reported errors were zero. Free-plan fitness is therefore
unproven; successful requests do not demonstrate sustained compliance. Keep the
preview protected and retain the old production environment. Isolate route costs
and compare after optimization before considering the public switch.

The query follows Cloudflare's
[Workers metrics example](https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/):

```graphql
query PreviewCPU($accountTag: string, $start: string, $end: string, $scriptName: string) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      workersInvocationsAdaptive(limit: 10, filter: {
        scriptName: $scriptName, datetime_geq: $start, datetime_leq: $end
      }) {
        sum { requests errors subrequests }
        quantiles { cpuTimeP50 cpuTimeP99 }
        dimensions { status }
      }
    }
  }
}
```

Unit verification:

```graphql
{ __type(name: "AccountWorkersInvocationsAdaptiveQuantiles") {
    fields { name description }
} }
```

## Management authentication

The preview's launcher supplies the stored OAuth access token explicitly, so an
expired token bypasses Wrangler's automatic refresh. The stored refresh token
successfully renewed the credential through the same OAuth refresh grant and
endpoint used by installed Wrangler 4.148.0. Credential values were withheld;
the configuration retained mode 0600. Python's default User-Agent received HTTP
403, while an explicit User-Agent allowed refresh. No site configuration or user
data changed during recovery. Automatic refresh in the launcher remains absent.

Remaining migration checks include route-specific CPU and memory, daily quotas
and stopping at limits, persistent metrics, real AI quality and device HEIC,
complete old-record/share migration, public SEO, dekita score transfer, and old
paid-resource retirement. No paid plan or old-service shutdown was performed.

## Static-assets experiment — 2026-10-09 JST

Deployed version: `cacbf9b8-5e19-4931-985b-b7794b2acd3e`.
Rollback version: `402d1c1d-c449-4c4a-a4ac-809f3f91d653`.
Allowlisted static resources use existing ASSETS after Basic authentication and
Host/method validation. All 14 assembled app modules matched original bytes.
Models, prompts, image preprocessing, metadata handling and postprocessing did
not change. Local and deployed `check.py --oauth` passed, including static body
equality, HEAD lengths, cache validation, security headers, APK filenames and
auth rejection. Forged Host is tested locally; Cloudflare rejects it at the edge.
Two medium reviews identified download-header and measurement failure-handling
issues; these were corrected and checked.

Route-tail experiments were incomplete and are not valid matched comparisons.
Before: 15/16 traces observed, with some HTTP500/outcome exception; successful
static requests observed 24–27ms. The exception cause is unproven.
After: 12/16 traces observed, all 16 HTTP responses 200; observed index.js CPU
6, 9, 10ms; libheif CPU 6, 8, 18, 6ms. This run overlapped HTTP validation, so
load was uncontrolled. Dynamic requests observed 21–503ms and readiness 270ms.
Missing traces prevent a full comparison. A later run failed during readiness
and produced an explicitly ineligible diagnostic.

`measure_cpu.py` uses a tail header filter to isolate operator probes. It retains
reduced route/sample/status/body-hash/timing/error fields, without raw logs or
credentials, and calls no external AI. Only complete successful records from one
version qualify; failed, missing, nonfinite and network-error samples do not.
The observed static reduction does not prove free-plan fitness. The migration
remains in progress; old production and data are retained.

## Complete route observation — 2026-10-09 JST

Read-only measurement window: `2026-10-08T18:58:20.925096Z` through
`2026-10-08T18:58:43.374118Z`, version
`cacbf9b8-5e19-4931-985b-b7794b2acd3e`, using
`measure_cpu.py --samples 2`. All 12 requested traces and the subscription
probe were observed. All returned HTTP200 with outcome `ok`, no exceptions,
and the same version. Bodies had consistent SHA256 values within each route.
The measurement's eligibility check passed. No external AI was called.

| Route | First measured request CPU (ms) | Subsequent request CPU (ms) |
| --- | ---: | --- |
| `/health` | 302 | 16, 29 |
| `/api/me` (signed out) | 206 | 270, 15 |
| `/assets/index.js` | 12 | 6, 5 |
| `/vendor/photo/libheif.mjs` | 4 | 5, 4 |

The subscription readiness request used 285ms CPU. “Subsequent” means request
order, not a verified warm isolate: tail does not establish isolate reuse or
attribute initialization separately. The 270ms later `/api/me` request must
not be assigned to cold start without additional evidence. No simultaneous
validation was launched by this session; other preview traffic was not ruled
out. This is a complete observation of the current version, not a matched
before/after comparison or a load/AI/photo-memory test.

Dynamic CPU exceeded 10ms in every measured dynamic request. Static subsequent
requests used 4–6ms, while the first index.js request used 12ms. Thus neither
dynamic nor whole-app Free-plan compliance is established. The prior HTTP500
was not reproduced; its cause remains unknown. The next diagnostic should
separate Python entrypoint/native response, minimal ASGI, and full middleware
costs without changing identification conditions or user data.

Before this run, the management launcher failed authentication with Cloudflare
code 9109 and the measurement correctly returned an ineligible empty diagnostic.
Ordinary Wrangler `whoami` did not discover authentication. The existing refresh
grant was renewed using the installed Wrangler's client ID and token endpoint;
only the operator credential file changed, retaining mode 0600. No credential
values were printed or committed. Automatic refresh in the launcher remains
unimplemented. No deployment, user-data migration, public switch, paid-plan
change, or old-service shutdown occurred.
