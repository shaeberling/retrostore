import assert from "node:assert/strict";
import test from "node:test";

import {
  API_EXACT_PATHS,
  API_PREFIX_PATHS,
  STATIC_CONTENT_TYPES,
} from "../src/routes.generated.mjs";
import { classifyPath } from "../src/routing.mjs";

test("generated route counts remain contract-closed", () => {
  assert.equal(Object.keys(STATIC_CONTENT_TYPES).length, 79);
  assert.equal(API_EXACT_PATHS.length, 17);
  assert.equal(API_PREFIX_PATHS.length, 2);
});

test("static routes carry legacy content types", () => {
  assert.deepEqual(classifyPath("/"), { origin: "static", contentType: "text/html" });
  assert.deepEqual(classifyPath("/favicon.ico"), {
    origin: "static",
    contentType: "text/plain",
  });
  assert.deepEqual(classifyPath("/js/trsemu-1.5.js"), {
    origin: "static",
    contentType: "application/javascript",
  });
});

test("only frozen API exact and prefix paths reach Cloud Run", () => {
  assert.deepEqual(classifyPath("/api/listApps"), { origin: "api" });
  assert.deepEqual(classifyPath("/assets/screenshots/abc"), { origin: "api" });
  assert.deepEqual(classifyPath("/s/abc"), { origin: "api" });
  assert.deepEqual(classifyPath("/api/listAppsExtra"), { origin: "app-engine" });
  assert.deepEqual(classifyPath("/downloadapp/extra"), { origin: "app-engine" });
});

test("hardware and unknown paths pass through to App Engine", () => {
  for (const path of ["/card", "/card/update", "/trs-io", "/reportapp", "/unknown"]) {
    assert.deepEqual(classifyPath(path), { origin: "app-engine" });
  }
});
