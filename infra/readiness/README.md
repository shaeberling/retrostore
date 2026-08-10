# RetroStore migration decision register

`decision-register.json` is the concise source of truth for the choices that
still require an operator. The two candidate hostnames, candidate resource
creation, go/no-go owner, and rollback operator are resolved. It assigns no
alert recipient, retention clock, report workflow, or production authority.
Validate it offline with:

```shell
python3 infra/readiness/validate.py
```

The validator cross-checks the approved hostnames and owners against the route
plan, the resolved comparison and cutover policy against the thresholds, and
unapproved retention status against the no-delete proposal. CI fails if one of
those sources silently diverges.

Private implementation, tests, comparisons, and drift audits may continue. The
approved candidate-only load balancer, certificate, public services, static
bucket, and public IAM now exist. DNS is intentionally pending while the domain
moves providers. Notification channel selection is required before production
cutover. Production traffic changes, App Engine retirement, and legacy deletion
remain unavailable until their exact decisions and evidence gates are satisfied.

`retrostore.contract.migration_readiness` combines this register with the
sanitized comparison streak, private-service drift, comparator-pipeline drift,
real-client, and 338-scenario transport artifacts. It has no cloud client or apply mode. The
2026-08-10 evaluation passed the private engineering checks. The parallel HTTP
front door separately passes 350/350 pre-DNS scenarios, but HTTPS, public
real-client, and authenticated admin validation must follow DNS/certificate
activation. The remaining explicit decisions and those live gates still block
production cutover and App Engine retirement.
