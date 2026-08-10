import assert from "node:assert/strict";
import test from "node:test";

import { handleRequest } from "../src/worker.mjs";

const env = {
  STATIC_ORIGIN: "https://static.example",
  API_ORIGIN: "https://api.example",
  APP_ENGINE_ORIGIN: "https://legacy.example",
  APP_ENGINE_MODE: "origin-url",
  ADMIN_ORIGIN: "https://admin.example",
  ADMIN_HOSTS: "admin-next.retrostore.org,admin.retrostore.org",
};

test("plain HTTP API requests are proxied without a redirect or body changes", async () => {
  const requestBody = new Uint8Array([0, 1, 255, 7]);
  const request = new Request("http://next.retrostore.org/api/listApps?page=1", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: requestBody,
  });
  const response = await handleRequest(request, env, async (originRequest) => {
    assert.equal(originRequest.url, "https://api.example/api/listApps?page=1");
    assert.equal(originRequest.method, "POST");
    assert.equal(originRequest.redirect, "manual");
    assert.equal(originRequest.headers.get("accept-encoding"), "identity");
    assert.equal(originRequest.headers.get("x-retrostore-original-proto"), "http");
    assert.deepEqual(new Uint8Array(await originRequest.arrayBuffer()), requestBody);
    return new Response(new Uint8Array([10, 20, 30]), {
      headers: { "Content-Type": "application/x-protobuf" },
    });
  });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("location"), null);
  assert.equal(response.headers.get("content-type"), "application/x-protobuf");
  assert.equal(response.headers.get("content-length"), "3");
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), new Uint8Array([10, 20, 30]));
});

test("static responses receive the frozen legacy MIME type", async () => {
  const response = await handleRequest(
    new Request("https://next.retrostore.org/js/trsemu-1.5.js"),
    env,
    async (originRequest) => {
      assert.equal(originRequest.url, "https://static.example/js/trsemu-1.5.js");
      return new Response("javascript", { headers: { "Content-Type": "text/javascript" } });
    },
  );
  assert.equal(response.headers.get("content-type"), "application/javascript");
});

test("unknown paths use the explicit App Engine origin in preview mode", async () => {
  const response = await handleRequest(
    new Request("https://preview.example/card/current?model=1"),
    env,
    async (originRequest) => {
      assert.equal(originRequest.url, "https://legacy.example/card/current?model=1");
      return new Response("legacy");
    },
  );
  assert.equal(await response.text(), "legacy");
});

test("candidate DNS mode keeps the original URL for App Engine pass-through", async () => {
  const response = await handleRequest(
    new Request("http://next.retrostore.org/trs-io/image"),
    { ...env, APP_ENGINE_MODE: "dns-origin" },
    async (originRequest) => {
      assert.equal(originRequest.url, "http://next.retrostore.org/trs-io/image");
      return new Response("legacy");
    },
  );
  assert.equal(await response.text(), "legacy");
});

test("redirect responses are returned without being followed", async () => {
  const response = await handleRequest(
    new Request("https://next.retrostore.org/community"),
    env,
    async () => new Response(null, { status: 302, headers: { Location: "https://example.org" } }),
  );
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "https://example.org");
  assert.equal(await response.text(), "");
});

test("admin host routing is independent of public paths", async () => {
  await handleRequest(
    new Request("https://admin-next.retrostore.org/users"),
    env,
    async (originRequest) => {
      assert.equal(originRequest.url, "https://admin.example/users");
      return new Response("admin");
    },
  );
});

test("invalid origin configuration fails closed", async () => {
  const response = await handleRequest(
    new Request("http://next.retrostore.org/api/listApps"),
    { ...env, API_ORIGIN: "http://api.example" },
    async () => assert.fail("origin should not be fetched"),
  );
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
