import {
  API_EXACT_PATHS,
  API_PREFIX_PATHS,
  STATIC_CONTENT_TYPES,
} from "./routes.generated.mjs";

const API_EXACT = new Set(API_EXACT_PATHS);

export function classifyPath(pathname) {
  const staticContentType = STATIC_CONTENT_TYPES[pathname];
  if (staticContentType !== undefined) {
    return { origin: "static", contentType: staticContentType };
  }
  if (API_EXACT.has(pathname) || API_PREFIX_PATHS.some((prefix) => pathname.startsWith(prefix))) {
    return { origin: "api" };
  }
  return { origin: "app-engine" };
}
