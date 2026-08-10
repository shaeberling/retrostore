# RetroStore migration decision register

`decision-register.json` is the concise source of truth for the choices that
still require an operator. It assigns no owner, recipient, hostname, retention
clock, report workflow, or production authority. Validate it offline with:

```shell
python3 infra/readiness/validate.py
```

The validator cross-checks the pending hostname/owner state against the route
plan, provisional soak/canary status against the monitoring thresholds, and
unapproved retention status against the no-delete proposal. CI fails if one of
those sources silently diverges.

Private implementation, tests, comparisons, and drift audits may continue.
Load balancers, certificates, DNS, public IAM, traffic changes, App Engine
retirement, and legacy deletion remain unavailable until their exact decisions
and evidence gates are satisfied.
