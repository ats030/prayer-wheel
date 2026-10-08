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

## Local runtime decomposition — 2026-10-09 JST

Added localhost-only diagnostic comparisons to the existing synthetic app probe.
The production preview was not changed or deployed. The local bundle was
`c7c06d8155ab873cf3f9c54d7e90b75523105eb361de4d5c4e1ac2e05bee334c`;
all 14 assembled app modules remained byte-identical to the originals.

Eight cases, five alternating-order rounds, and 20 requests per capture produced
40 complete captures / 800 checked HTTP200 responses. Median local active sampled
time per request: native Python response 4.924ms, minimal ASGI 6.063ms, minimal
FastAPI async/sync 5.938/6.154ms, existing health/me router plus required cleanup
stack 5.975/5.930ms, full app health/me 9.928/9.849ms. The full app retains its
original middleware. The probe-specific revision middleware was removed from
the comparison; revision headers remain on ordinary `/health` responses.

These are local Inspector samples at 1000µs intervals, not production CPU
accounting. The roughly 4ms difference between router and full app identifies
app wrapping as a candidate for further investigation, without allocating the
difference to individual middleware or exception handling. The local probe has
no Google OAuth configuration and does not reproduce the preview's Basic auth,
isolate initialization, AI identification, photo transfer, or memory use. It
does not explain production 200–300ms requests or the prior HTTP500. Full results,
method and limitations are in the
[local probe README](../cloudflare-app-probe/README.md#python--asgi--アプリ全体の切り分け).

Validation passed: 58 public resources/API/header/HEAD/D1-read boundaries;
original and native-parsed synthetic identification hashes/metadata/input
rejections; missing secret/DB startup refusal; profiling disabled rejects all
eight runtime diagnostics; diagnostic POST404 and nonlocal Host403. Medium code
review flagged single-request profiling quantization; batching 20 requests per
capture addressed it, the repeated measurement passed, and a medium follow-up
review reported no concrete remaining correctness issue. No real AI calls or
user data were used. This is internal diagnostic work, with no public changelog
or production behavior change.

## Runtime identity and snapshot preparation — 2026-10-09 JST

Instrumented version: `d360ac3a-1170-41d7-b606-842b76c97d98`.
Current optimized version: `851e9a73-87ad-4b96-9fd8-580ed77d8bf2`.
Optimization rollback: instrumented version above; entire experiment rollback:
`cacbf9b8-5e19-4931-985b-b7794b2acd3e`.

Authenticated requests with the operator measurement marker receive an
ephemeral UUID and the runtime's fetch invocation number. The UUID is generated
in request context; no event loop/task is started and no invocation is counted
in the deployment snapshot. Ordinary/unauthenticated/invalid-marker responses
do not carry these headers. The marker selects measurements; Basic remains the
authorization boundary. Counts include early rejected requests. Neither value
identifies a user or photo. This establishes repeated requests to the observed
Python runtime, without asserting a physical host or regional placement.

Before: `2026-10-08T19:40:38.872778Z`–`19:41:14.325708Z`.
After: `2026-10-08T19:45:23.480131Z`–`19:45:58.049901Z`.
Each run captured 24/24 requested traces, all HTTP200/outcome `ok`, no exceptions,
and one version. Within each run, all runtime UUIDs were valid and invocation
counts strictly increased whenever an identity recurred. Four identities were
observed in each run. No remote validation was run concurrently by this session.

| Observation (CPU ms) | Instrumented baseline | Snapshot preparation |
| --- | --- | --- |
| Measured first health invocations | 206, 133 | 62, 29 |
| Measured first me invocation | 301 | 47 |
| Repeated health invocations (4 requests) | 14–30; median 18 | 11–26; median 18.5 |
| Repeated me invocations (5 requests) | 8–14; median 10 | 10–26; median 13 |
| index.js (6 repeated requests) | 3–13; median 4.5 | 3–6; median 5 |
| libheif (6 repeated requests) | 5–19; median 9 | 3–12; median 3.5 |

The baseline's later-in-route 133/206/301ms requests were invocation 1 in different
runtimes, resolving the previous uncertainty about whether route order implied
reuse. In the optimized observation no requested trace exceeded 62ms. This is
consistent with less first-request initialization, but the small sequential
runs use different runtimes and do not control physical CPU or other users'
traffic. It is not a causal allocation between the two preparation changes, a
universal cold-start benchmark, or proof of Free-plan compliance. Repeated health
and me still exceed 10ms. AI, uploads, memory, quotas and persistent metrics were
not tested; the prior HTTP500 cause remains unresolved.

The change moves the pinned AnyIO 4.15.1 asyncio backend's lazy import and the
unchanged FastAPI middleware stack construction into module startup. It uses
the existing private resolver with an explicit backend name, without opening
an event loop. Stack construction occurs after the existing identify FormData
route wrapping. All 14 assembled app modules are byte-identical to the original
app, and models/prompts/photo preprocessing/postprocessing remain unchanged.
Reported deployment startup times were 4258ms before and 2955ms after; these
deployment values are separate from request CPU and are not an isolate startup
comparison. Dependency updates require revalidation of the private resolver.

Reduced evidence artifacts: [baseline JSON](cloudflare-cpu-isolate-baseline.json)
and [snapshot preparation JSON](cloudflare-cpu-preloaded.json). They retain only
route/sample/status/hash/timing/version/ephemeral identity fields, not credentials,
raw logs, cookies, user data or request headers. Subscription readiness is excluded
from the comparison table: the baseline collector reused `-1` for retry attempts;
the collector now uses unique negative IDs and rejects delayed unmatched events.
The 24 numbered measurement requests had distinct sample IDs in both runs.

Local and remote `check.py --oauth` passed before and after preparation. Checks
include UUID/counter progression and absence on ordinary/unauthenticated requests,
Basic and OAuth boundaries, current bundle/source hashes, static body/HEAD/security
headers, diagnosis404 and oversized upload400. Invalid/missing/duplicate/reversed
counters and nonfinite CPU were rejected by the collector check. Both medium
reviews reported no concrete bug (the first review attempt failed due to the
sandbox and was rerun). The preview changelog was deployed with the performance
experiment; its Drive verification wording now reflects the user's successful
manual check. Old production/data remain intact; no public switch, paid plan,
external AI call or user-data migration occurred.

## Reviewed policy adapters in protected preview (2026-10-09 JST)

Deployed `6ea2d2c0-c519-4a8c-ae44-87968cfb4e83`; rollback is
`851e9a73-87ad-4b96-9fd8-580ed77d8bf2`. The reviewed Workers-only ASGI adapters
call the unchanged security_headers, require_login and keep_one_origin policies
in their existing order. TrustedHost and FastAPI's cleanup middleware remain.
AnyIO startup preparation and the existing identify FormData wrapper remain.
All 15 allowlisted assembled modules are byte-identical to their original files;
models, prompts, photo conditions and postprocessing did not change.

The first run (20:15:11–20:16:23 UTC) returned HTTP200 for all 24 requests but
captured only 23 tails. The missing tail belonged to a runtime invocation 1 on
me. It exited 2 and is ineligible for a successful comparison. Observed health
CPU included 12/14ms; this counterexample is retained rather than discarded.
No exceptions occurred in the captured tails. The missing request CPU is unknown.

The retry (20:16:44–20:17:15 UTC) captured 24/24 plus readiness; all HTTP200,
outcome ok, no exceptions, one deployed version and valid runtime sequences.
Every measured invocation was greater than 1: this run does not measure cold start.

| Route | Previous snapshot-prepared observation, invocation >1 | Adapter retry, invocation >1 |
|---|---:|---:|
| health | 11–26ms (4 requests) | 3–9ms (6 requests) |
| signed-out me | 10–26ms (5 requests) | 3–7ms (6 requests) |
| index.js | 3–6ms (6 requests) | 3–6ms (6 requests) |
| libheif | 3–12ms (6 requests) | 3–5ms (6 requests) |

Sequential observations used different runtimes and did not control hardware,
traffic or the number of prior invocations. These values support lower observed
dynamic request cost, not a guaranteed upper bound or whole-app Free compliance.
The incomplete run still contains health above 10ms. Real AI, authenticated
data routes, uploads, memory, quotas and persistent metrics remain unmeasured.
The historical HTTP500 cause remains unknown and did not reproduce here.

Evidence: [incomplete run](cloudflare-cpu-policy-incomplete.json) and
[complete retry](cloudflare-cpu-policy.json), retaining reduced metadata only.
Validation: 19 policy parity tests passed; local and deployed `check.py --oauth`
passed; all 15 modules matched source bytes; medium code review found no actionable
auth/security/response/integration defect. The preview changelog was deployed.
Management OAuth refresh succeeded without printing credentials (0600 retained);
automatic launcher refresh is still absent. Old production/data remain intact;
no paid plan, general-public switch, external AI call or user-data migration.
