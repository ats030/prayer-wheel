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
