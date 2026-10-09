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

## Synthetic provider serialization and native streams (2026-10-09 JST)

The new [transport diagnostic](../cloudflare-transport-probe/README.md) isolates
the remaining large-photo transfer cost without external AI, Google, DB or real
user data. Input is seed=3 JPEG, 1600x1600, 1,997,593 bytes, with one or three
photos. The prompt and generation settings come from the unchanged actual
`vision.identify_gemini` function through a no-network capture shim. Checked
twins verify complete payload semantics and reconstructed photo bytes.

Python payload construction had local active-sample medians 52.594/147.740ms
for 1/3 photos. Switching base64/JSON to JS after conversion into Python bytes
increased same-run medians from 54.737/148.588 to 82.364/234.996ms; reject this
approach. Keeping the photos inside JS reduced the local medians to
25.769/70.103ms. Pure streaming in the local development bridge produced large
anonymous/program samples and GC; these samples cannot be mapped to billed CPU.
All local figures are approximations, not Free-plan judgments. Small JS paths
use 20-request batches x5; measured direct/stream cases have 400 checked HTTP200
requests. Local sources and provider bundle hashes are checked before runs.

To resolve the local ambiguity, a separate Basic-protected synthetic Worker was
temporarily deployed. It has no outbound fetch, DB, provider key or user storage.
The real app preview stayed at `6ea2d2c0-c519-4a8c-ae44-87968cfb4e83`.

| Synthetic route | JS identity-transform version | Native stream version |
|---|---:|---:|
| health | 0–1ms | 0–1ms |
| assemble 1 photo | 23–49ms | 23–35ms |
| assemble 3 photos | 72–101ms | 66–102ms |
| transfer provider JSON, 1 photo | 25–54ms | 0ms, all 6 requests |
| transfer provider JSON, 3 photos | 98–168ms | 0ms, all 6 requests |

Transform run: version `eb66158e-55d7-4be3-8a87-43b3fdf8ad14`, UTC
20:41:32–20:42:28. Native run: version `f759130e-a01d-4582-a5f6-90a6d48e4fca`,
UTC20:45:42–20:46:29. Each collected30/30 plus readiness, all HTTP200/outcome ok,
no exceptions, one version and valid runtime counter sequences. Every wire
response SHA equals the exact original synthetic provider JSON. Payload result
SHA matches expected photo SHA/serialized-wire SHA/length. Native run checks
current transport/wrapper source SHA in every response and the provider bundle
SHA in fixture provenance. The transform run payload SHA was also verified
against the expected complete fixture after collection.

0ms is the emitted accounting value, not proof of mathematically zero CPU.
Runs used different runtimes, hardware and network conditions. The native
streaming change uses the original native request body, avoiding the JS identity
TransformStream required by the local development bridge, and avoids an extra
Request/Response wrapper. UTF-8 Basic encoding was corrected in the same bounded
experiment. Do not allocate the measured difference to one isolated factor.

This supports moving large payload assembly into the browser and transferring
it natively. It does not prove the full app works within Free limits: Google
authentication, provider selection, existing photo/quality validation, actual AI,
postprocessing, persistence and quotas are excluded. These semantics must be
preserved when integrating; this echo endpoint is not an acceptable production
AI proxy. The standard app collector regression captured8/8 plus readiness
without errors; signed-out me on runtime invocation1 still consumed28ms. Python
cold/dynamic request costs therefore remain a material full-app issue.

Validation includes local original/native payload parity for1/3 images and input
rejects;13 flag-OFF diagnostic rejects; missing secret/DB startup rejects; local
wrapper Basic/Host/Unicode/no-diagnostics checks; remote401/current SHA/no ordinary
runtime IDs/404 diagnostics checks; unchanged default collector CLI. Medium
reviews found missing build wiring/HTTP timeouts and UTF-8 auth/stale provider
fixtures, all corrected before handoff. HTTP waits and inspector operations are
bounded, with cleanup on failure. Wrangler was4.149.0 throughout these new runs;
pywrangler's unpinned npx changed the shared cache from4.148.0. Version pinning is
tracked separately as `ats030-g1gd1`; this is not an app dependency change.

Artifacts: [local approximations](cloudflare-transport-local.json),
[transform accounting](cloudflare-transport-remote-transform.json),
[native accounting](cloudflare-transport-remote-native.json), and
[default collector regression](cloudflare-cpu-collector-regression.json).
They contain reduced measurements, hashes and ephemeral runtime IDs, no secrets,
raw logs, cookies, real photos or user records.

The temporary Worker was subsequently set to `workers_dev:false` (version
`19b86850-7a7e-4fb1-962d-ffdbe1df9d81`); its external health URL returned404.
The real app, old production and data remain intact; no paid plan/public switch,
external AI fee or data migration occurred. This operator-only diagnostic is
exempt from the real app changelog; integration must have its own release note.

Official constraints checked2026-10-08:
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/#cpu-time)
specify10ms Free CPU, occasional isolate flexibility and termination on repeated
overruns. Successful high-CPU responses are not proof of Free compliance. Python
interop uses the [official FFI](https://developers.cloudflare.com/workers/languages/python/ffi/).

## Native input validator accounting, 2026-10-09

The integrated validator remains OFF in the real app. A separate Basic/Host
protected diagnostic called the exact `worker_transport.mjs` `validatePayload`
with the original Python-generated Gemini template and synthetic JPEGs of
1,997,593 bytes each. It made zero external AI calls and reflected no input.
The collector verified all four source/template SHA fingerprints, response
bytes, version and runtime sequence. All18 numbered requests plus readiness
succeeded without exceptions; the reduced artifact is
[native validation accounting](cloudflare-native-validation-remote.json).

Measured version: `2cba20c6-585d-4f20-8b47-0a969554994a`.
Health CPU was0ms for all6 requests. Photo1 CPU was25,30,29,47,27,28ms;
photo3 CPU was79,78,81,82,71,116ms. Even this isolated validation path exceeds
the Free10ms CPU allowance. HTTP200 does not demonstrate Free suitability.
All recorded runtime invocation numbers exceed1: this is not cold-start proof.
Python application authentication/report/quality checks, multipart ingestion,
AI, postprocessing, persistence and memory consumption remain unmeasured here.
Earlier bare native forwarding measurements do not cover this validator cost.

The temporary diagnostic was disabled with `workers_dev:false` and
`preview_urls:false`, version `91ebd536-4547-41da-aecc-9e19cb5eeb84`;
external health returned404 and the temporary0600 secret file was removed.
The real preview/old app and user data were unchanged. No paid plan, general
public switch or AI fee occurred. Local boundary/tamper tests and a medium
code review passed. Operator-only diagnostics have no user-facing changelog.

Remaining work on `ats030-paskw`: optimize the full JSON parse/stringify and
whole-photo base64 decode while preserving input rejection semantics, rerun
differential/edge tests and real CPU accounting, then validate full app costs
before enabling native transport. No optimization has yet been implemented.

## JavaScript session verification experiment, 2026-10-09

The next bounded experiment reused the existing Basic/Host-protected diagnostic
with a separate random synthetic HMAC key. `worker_session.mjs` reads the exact
existing Python-issued session format using Web Crypto HMAC-SHA256. Differential
tests against actual `auth.py` cover valid UTF-8 sessions, forgery, expiry, invalid
signature encodings and wrong keys; oversized cookies are additionally rejected.
No real session key/cookie, OAuth credential, Google request, database or AI was
used. Availability was simulated configured state, not a Google health check.
The diagnostic response helper is not a complete replacement for real `/api/me`
configuration/reason handling. Existing app deployment remains unchanged.

Measured version `82cafde4-b1fc-4504-8ce9-079ba90f7911` yielded30/30 successful
requests plus readiness, with correct source/wrapper SHA and exact response
hashes. Signed-out CPU was0ms for all6 samples. Signed-in CPU was0,0,0,1,1,0ms;
tampered0,1,0,0,0,0ms; expired0,0,1,0,0,0ms; health1,0,0,0,0,0ms.
Zero is accounting precision, not zero execution. All runtime invocation counts
exceed1; cold behavior remains unproven. These isolated synthetic results support
moving session reads out of Python but do not allocate the earlier Python28ms
to a particular cause or prove full-app Free fit. OAuth, DB, photos, result
processing, memory and persistence are excluded.

[Reduced accounting](cloudflare-session-native-remote.json) contains no secrets,
cookies or raw logs. Medium bounded review found no actionable defects; local
session differential and existing wrapper regressions passed. The diagnostic
was disabled, version `96ad98f6-d5d7-4557-9cc8-cffa587ca191`, with external404;
the temporary0600 secret file was removed. `workers_dev:false` and
`preview_urls:false` remain the committed defaults. Internal synthetic work has
no user-visible changelog. Remaining `ats030-paskw` work includes a real JS
entrypoint preserving Basic/Host/DB/config boundaries, cold/full auth accounting,
and the previously identified photo validation cost.

## Real preview JS session entrypoint, 2026-10-09

The existing protected URL now uses `cloudflare-preview/front.jsonc` and
`edge.mjs`. Only `GET /api/me` bypasses Python, behind `IKIMONO_JS_SESSION=1`.
Basic authentication, URL/header Host allowlist, fixed session key, required
D1/backend bindings, original3-setting Google availability/reasons, API security
headers and existing signed session format are retained. All other requests use
one fixed HTTP Service Binding to `ikimono-note-preview-backend`, preserving the
original public URL, headers, stream, redirects and repeated Set-Cookie. Google
callbacks/logout remain Python and keep the same origin/key/database. Native
photo transport remains OFF. The private backend has no workers.dev/preview URL
or route; external health returned404. The earlier diagnostic also remains404.

Active gateway: `1aa67de5-bd31-4f88-8636-ba2d70260e2d`; private Python:
`712fe511-afdb-4ec6-95d1-533cfac7e677`. Gateway bundle SHA:
`68ee29c8e8e5f63245f464a50506edeffcbf5e2edf7033fd8863816871bc3ed9`.
The gateway digest incorporates its source, shared session verifier, generated
security policy and intended Python bundle. `/health` verifies the actual Python
bundle before stamping gateway identity and returns503 for a stale backend.
`check.py --oauth --edge` verified both bundle identities plus original protected
pages/assets/source archives/settings/upload/OAuth-start contracts on the actual
URL. `/changelog` contains the dated session-status change. Actual Google login
was not repeated in this turn; no new OAuth configuration or user migration was
performed. The old production/local app remains unchanged.

Gateway tail accounting,18/18 plus readiness per run, allHTTP200/no exceptions,
current bundle/response hashes and monotonic runtime sequences:

- [Signed out](cloudflare-edge-session-out.json): `/api/me` CPU0,1,0,0,0,0ms.
  The readiness request was `/api/me` with runtime invocation1 and1ms CPU;
  two additional recorded session requests also had invocation1 (1ms and0ms).
  This demonstrates first requests for those observed gateway runtimes, not a
  universal cold-start guarantee or Python cold accounting.
- [Synthetic signed in](cloudflare-edge-session-in.json): `/api/me`
  CPU2,1,0,0,1,1ms; readiness1ms with invocation10. No cold signed-in proof.
  The short-lived synthetic cookie was generated in memory using the existing
  preview key and sent only to `/api/me`; it never created or queried a DB user.
- [Default collector regression](cloudflare-edge-collector-regression.json):
  unchanged CLI captured8/8 plus readiness successfully. Its default readiness
  remains `/health`; the new optional readiness path does not alter old callers.

Frontend CPU does not establish fallback CPU. A separate tail of the private
Python service, with requests still sent through the real gateway, captured
12/12 plus readiness, allHTTP200/no exceptions/current gateway+Python hashes:
[backend accounting](cloudflare-edge-backend.json). Its health CPU was
4,5,4,4,8,4ms; assets3,6,3,4,4,3ms; readiness9ms. The trace version is the
private backend, but response runtime IDs/counts belong to the gateway. Those
counts cannot prove Python cold behavior. These are separate request sets and
must not be added sample-by-sample or used to causally allocate the earlier28ms
Python measurement. Google OAuth, authenticated DB reads/writes, actual AI,
photo handling, postprocessing, persistent metrics and memory remain unproven.

Validation: local real JS/Python multi-worker check PASS; original Python
session-forgery pytest1PASS; actual Python sign/read differential PASS; real local
and remote HTTP comparison for UTF-8/signed-in/out/tamper/expiry PASS; JS boundary
tests cover Basic/Host/DB/backend/flag/config, zero Python calls for session API,
proxy body/redirect/repeated cookies and stale-backend rejection. Medium reviews
identified missing backend build, missing backend provenance validation and a
redirect-following credential risk in the test helper; all were fixed. Generated
output caused a dev rebuild loop; source-only custom-build watchers fixed it,
and local checks passed again. Local dev was stopped before final deployment.

Rollback is the retained `wrangler.jsonc` Python entrypoint: rebuild and deploy
with the same preview secrets, then run ordinary `check.py --oauth`. No paid
plan/add-on, real AI fee, user-data migration, general public switch or old-app
shutdown occurred. Internal connectivity uses the existing Workers service;
[cost/terms review](tool-license-cloudflare-service-binding.yaml) records the
conditional Free plan and remaining quota obligations. Service splitting does
not establish Free compliance. `ats030-paskw` remains in_progress for the photo
validation cost, full auth/identify/storage paths, memory/quota and full migration.

## Native photo validation candidate, 2026-10-09 (not enabled)

The unpublished `worker_transport.mjs` candidate removes whole uploaded JSON
parse/stringify and whole-photo Base64 decoding. It validates the exact canonical
frame against the authoritative template, checks all Base64 characters/padding,
and strictly decodes the JPEG header and tail. Count/size/dimensions/metadata,
prompt/config and fixed provider boundaries remain tested. Invalid UTF-8 is
intentionally rejected instead of silently matching a replacement character.
An independent frozen legacy validator provides differential acceptance tests;
targeted maximum-size, unused-bit, JPEG boundary and malformed-UTF8 tests pass.
The related Python/JS regression suite passes92 tests. Actual Workers rejection
checks pass without provider calls.

[Pre-BOM-fix candidate evidence](cloudflare-native-validation-ascii-remote.json)
captures18/18 plus readiness, allHTTP200/no exceptions/current source hashes and
monotonic runtime sequences. One-photo CPU was9,10,15,8,10,9ms; three-photo
CPU51,23,31,33,34,25ms. All runtime invocations exceed1: no cold or memory proof.
This still exceeds10ms before Python auth/quality, multipart, AI, postprocessing
or persistence. Native identify remainsOFF; the existing gateway/backend were
not redeployed. This is an experiment, not a Free-compatible release.

An [earlier whole-string candidate](cloudflare-native-validation-string-remote.json) observed7–13ms /18–43ms; the current candidate
is not established as fastest. A chunked-stream candidate was slower and had
incomplete tail evidence, so it was abandoned. The current candidate's first
run also missed one health trace; only the complete retry above supports its
CPU claim. Earlier measurements use different runtimes and do not establish
causal CPU allocation. Local resource reload briefly read an incomplete generated
file; stopping dev before building resolves the immediate failure. Atomic output
replacement is tracked separately as `ats030-l7vhn`.

No real AI, user-data migration, paid plan, public switch or old-service shutdown
occurred. Operator diagnostics and the disabled unpublished path are changelog
exempt. Remaining candidate selection/review and full migration stay on
`ats030-paskw`; do not enable this path on the strength of validation-only CPU.
Medium review found that TextDecoder stripped a photo-leading BOM, allowing a
noncanonical input. `ignoreBOM:true` now preserves it for rejection; an explicit
attack test and the92-test suite pass. Final source CPU was not remeasured;
the saved evidence is tied to the pre-fix source hash, not the final source.
Temporary diagnostic shutdown version `6f893e64-ee34-4de9-9b1f-5fbff8af5d8a`
has workers_dev/preview_urls false; external404 verified. Local dev was stopped
and the temporary0600 secrets file deleted.

## Browser-direct Gemini preview — 2026-10-09 JST

Protected preview only. Final gateway version `9c8561af-a754-4f14-ab9a-988bc7bb2c04`,
private Python version `420e3109-964d-4d4d-a206-fac1095f21c7`.
Gateway SHA `be634a0fff3ffe2df1bc827553a21640305bcb0c0cf6d37ab62f18dfe6697fc5`;
Python SHA `a568ed4a610415719965461c26e282d9612b2a98c3fea4b5563f977a10ff5756`.
Both Gemini flags are enabled; the earlier Worker photo relay remains OFF.

For new photos from the capture page, own-key Gemini without Pl@ntNet sends
prepared JPEGs and the key from the browser directly to the fixed Google API.
Only capture/quality reports and the provider reply reach this preview server.
Other providers, Pl@ntNet, and history re-identification retain the old paths.
Original production and user data were not switched or migrated.

Remote auth/OAuth-start/source/hash checks passed. Real Chromium on the final
URL used synthetic sessions, a synthetic key and intercepted Gemini HTTP for
1/3 photos. Current gateway SHA and JS engine were asserted for both APIs;
original result rendering and all photos/capture date committed to isolated
IndexedDB. No actual Gemini, Drive, or real Google login was performed in these
checks. The dated preview changelog was published with the behavior change.

[Complete initial context CPU](cloudflare-gemini-context-remote.json) contains
12/12 traces plus readiness from gateway `e319b493-635e-4d33-9d29-acd6d21d852c`.
All HTTP200/outcome ok/current measured hashes/JS engine/Python response bytes
matched. Prepare CPU was 3,3,1,1,4,1ms; empty-candidate result 1,0,2,1,1,1ms.
Some prepare requests were invocation1 (3/4ms). This historical run predates
taxonomy redirect/quota fixes and does not prove the final whole path fits Free.
Earlier combined health runs lost traces and were excluded. The collector now
retains reduced diagnostics, keeps files ineligible until provenance validation,
and measures the two native APIs with mandatory health readiness/backend hash.

The installed workerd rejected redirect:error before network I/O. The taxonomy
fetch now uses manual and refuses/cancels3xx; an actual workerd regression covers
Request construction and the redirect guard without external traffic.
[The subsequent taxonomy diagnostic](cloudflare-gemini-taxonomy-diagnostic.json)
has 12/12 traces from gateway `cb8cd66d-8aa8-4c35-b678-2d50c3dc102b`, but varying
candidate results failed the expected body hash, so it is ineligible. A result
request used13ms CPU. Operator-only temporary checks observed upstream HTTP429;
those temporary diagnostics were removed. Final remote HTTP confirmed explicit
result429/Retry-After60 instead of an empty successful result. An isolate-local
cooldown suppresses further uncached lookups; no cross-isolate or persistent
cache/quota contract was introduced.

[CORS preflight](cloudflare-gemini-cors.json) is OPTIONS-only: no key or photo,
HTTP200 with the preview origin/POST/header names allowed. This is not proof of
model availability, API-key validity, or actual generation.

121 related pytest tests, JS edge/handler and actual workerd checks passed.
The initial medium review's missing evidence link was fixed. The later required
medium review was attempted but interrupted by the Codex usage cap; it did not
complete. Final scoped changes were manually reviewed, without claiming an
automated review pass. Remaining work includes final full taxonomy/AI CPU,
maximum replies/cold/memory, actual Gemini and Drive behavior, migration/shares,
and global/daily quotas. No paid plan, general public switch or old shutdown.

## Current GBIF candidate-result measurement — 2026-10-10 JST

The user confirmed identification succeeded on the protected preview after the
GBIF fallback fix. This is a user report, without a captured photo, AI response,
photo count or provider selection. Earlier issue notes also record successful
Google login, Drive save and reload in another browser; these reports are distinct
from the operator's synthetic checks.

[Current candidate CPU evidence](cloudflare-gemini-gbif-current.json) has all6/6
traces plus readiness from gateway `fafc1f6d-5dbc-4092-8bfa-1ba881555b61`, SHA
`61c3d2e7f094a55be2320019a28d6e61416f7edfd9ef460f30bb3a027e2ddd1d`.
All HTTP200, runtime sequences, JS execution, gateway/backend hashes and Python
response hashes passed. Synthetic three-photo reports and three known Latin
names were used; taxonomy HTTP was real, but no photo, AI key, Gemini call or
Drive operation was performed. Prepare CPU was1,2,2ms; candidate-result CPU was
3,3,3ms. All measured invocation counts exceed1, so this is not cold-start evidence.

The reference collector now obtains real matching taxa from both sources and
computes the exact Python output for each available source combination. Eight
reference hashes cover the three candidates' iNaturalist/GBIF combinations;
other changes to response bytes still fail. Lookup failures and nonmatching
names do not become references. Incomplete or mismatched evidence stays
ineligible, with its reduced diagnostic retained.

[The first run](cloudflare-gemini-gbif-parity-diagnostic.json) collected8/8 traces
but failed its single-source response hash; result CPU included13ms. It is not
an eligible success comparison or evidence that Free fits. After correcting
the reference collector, [the next run](cloudflare-gemini-gbif-missing-traces.json)
lost3/8 traces and was also excluded. The complete final run does not erase
those observations or guarantee every runtime/cache state fits the Free budget.
Cloudflare's [current limits](https://developers.cloudflare.com/workers/platform/limits/)
still specify10ms CPU per Free invocation; checked2026-10-09 UTC.

Measurement regression/core/fallback tests17 passed. Required medium review of
the collector and tests found no actionable issue; its attempted test command
was blocked by sandbox setup, while the main agent's targeted run passed.
This changes operator tooling only, with no app behavior or deployment change;
the user-facing changelog is exempt. Remaining work is cold/uncached and maximum
input CPU/memory, the other Python paths, daily limits, old records/shares and
complete migration. The old service and protected-preview deployment remain.
