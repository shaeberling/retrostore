import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const config = JSON.parse(
  await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"),
);
const baseline = JSON.parse(
  await readFile(new URL("../candidate-baseline.json", import.meta.url), "utf8"),
);

test("default deployment is isolated from RetroStore custom domains", () => {
  assert.equal(config.name, "retrostore-front-door-preview");
  assert.equal(config.workers_dev, true);
  assert.equal(config.routes, undefined);
});

test("candidate deployment owns only the two approved custom domains", () => {
  assert.deepEqual(config.env.candidate.routes, [
    { pattern: "next.retrostore.org", custom_domain: true },
    { pattern: "admin-next.retrostore.org", custom_domain: true },
  ]);
  assert.equal(config.env.candidate.vars.APP_ENGINE_ORIGIN, "https://retrostore.org");
  assert.equal(config.env.candidate.vars.APP_ENGINE_MODE, "origin-url");
});

test("all cross-provider origins use HTTPS", () => {
  for (const vars of [config.vars, config.env.candidate.vars]) {
    for (const name of ["STATIC_ORIGIN", "API_ORIGIN", "APP_ENGINE_ORIGIN", "ADMIN_ORIGIN"]) {
      assert.equal(new URL(vars[name]).protocol, "https:");
    }
  }
});

test("deployed candidate baseline matches config and denies production authority", () => {
  assert.deepEqual(
    baseline.cloudflare.custom_domains,
    config.env.candidate.routes.map(({ pattern }) => pattern),
  );
  assert.equal(baseline.origins.static, config.env.candidate.vars.STATIC_ORIGIN);
  assert.equal(baseline.origins.api, config.env.candidate.vars.API_ORIGIN);
  assert.equal(baseline.origins.admin, config.env.candidate.vars.ADMIN_ORIGIN);
  assert.equal(
    baseline.origins.app_engine_fallback,
    config.env.candidate.vars.APP_ENGINE_ORIGIN,
  );
  assert.equal(baseline.cloudflare.production_route_attached, false);
  assert.equal(baseline.production.dns_changed, false);
  assert.equal(baseline.production.app_engine_authoritative, true);
});
