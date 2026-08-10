import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const config = JSON.parse(
  await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"),
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
