import { classifyPath } from "./routing.mjs";

const BODYLESS_STATUSES = new Set([101, 204, 205, 304]);
const HOP_BY_HOP_RESPONSE_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

export default {
  async fetch(request, env) {
    return handleRequest(request, env, fetch);
  },
};

export async function handleRequest(request, env, fetchImpl) {
  try {
    const incomingUrl = new URL(request.url);
    const adminHosts = new Set(
      String(env.ADMIN_HOSTS ?? "")
        .split(",")
        .map((host) => host.trim().toLowerCase())
        .filter(Boolean),
    );

    if (adminHosts.has(incomingUrl.hostname.toLowerCase())) {
      return proxyFixedLength(request, requiredOrigin(env, "ADMIN_ORIGIN"), undefined, fetchImpl);
    }

    const route = classifyPath(incomingUrl.pathname);
    if (route.origin === "static") {
      return proxyFixedLength(
        request,
        requiredOrigin(env, "STATIC_ORIGIN"),
        route.contentType,
        fetchImpl,
      );
    }
    if (route.origin === "api") {
      return proxyFixedLength(request, requiredOrigin(env, "API_ORIGIN"), undefined, fetchImpl);
    }

    const appEngineOrigin =
      env.APP_ENGINE_MODE === "dns-origin"
        ? undefined
        : requiredOrigin(env, "APP_ENGINE_ORIGIN");
    return proxyFixedLength(request, appEngineOrigin, undefined, fetchImpl);
  } catch {
    return new Response("Bad Gateway\n", {
      status: 502,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
      },
    });
  }
}

async function proxyFixedLength(request, origin, contentType, fetchImpl) {
  const originRequest = await buildOriginRequest(request, origin);
  const upstream = await fetchImpl(originRequest);
  const headers = new Headers(upstream.headers);
  for (const name of HOP_BY_HOP_RESPONSE_HEADERS) {
    headers.delete(name);
  }
  if (contentType !== undefined) {
    headers.set("Content-Type", contentType);
  }

  if (request.method === "HEAD" || BODYLESS_STATUSES.has(upstream.status)) {
    return new Response(null, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  }

  const body = new Uint8Array(await upstream.arrayBuffer());
  headers.delete("Content-Length");
  headers.set("Content-Length", String(body.byteLength));
  return new Response(body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
    encodeBody: "manual",
  });
}

async function buildOriginRequest(request, origin) {
  const incomingUrl = new URL(request.url);
  const targetUrl = origin === undefined ? incomingUrl : new URL(incomingUrl.pathname + incomingUrl.search, origin);
  const headers = new Headers(request.headers);
  headers.delete("Content-Length");
  headers.delete("Host");
  headers.set("Accept-Encoding", "identity");
  headers.set("X-Retrostore-Original-Host", incomingUrl.host);
  headers.set("X-Retrostore-Original-Proto", incomingUrl.protocol.slice(0, -1));

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = new Uint8Array(await request.arrayBuffer());
  }
  return new Request(targetUrl, init);
}

function requiredOrigin(env, name) {
  const value = env[name];
  if (typeof value !== "string" || value === "") {
    throw new Error(`Missing ${name}`);
  }
  const url = new URL(value);
  if (url.protocol !== "https:") {
    throw new Error(`${name} must use HTTPS`);
  }
  return url;
}
