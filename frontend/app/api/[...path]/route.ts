import { NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// The browser only sees same-origin URLs. Cookie authentication and streams pass through unchanged.
async function proxy(request: NextRequest) {
  const base = process.env.BACKEND_URL || "http://localhost:8000";
  const target = new URL(
    request.nextUrl.pathname + request.nextUrl.search,
    base,
  );
  const headers = new Headers();
  for (const key of [
    "content-type",
    "cookie",
    "origin",
    "x-requested-with",
    "range",
  ]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  if (headers.get("x-requested-with") === "narcissus") {
    headers.set("x-requested-with", process.env.BACKEND_REQUEST_MARKER || "narcissus");
  }
  const init: RequestInit & { duplex?: string } = {
    method: request.method,
    headers,
    cache: "no-store",
    signal: request.signal,
  };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }
  try {
    const upstream = await fetch(target, init);
    const outgoing = new Headers();
    for (const key of [
      "content-type",
      "content-range",
      "accept-ranges",
      "content-disposition",
      "x-request-id",
      "x-content-type-options",
      "content-security-policy",
    ]) {
      const value = upstream.headers.get(key);
      if (value) outgoing.set(key, value);
    }
    for (const cookie of upstream.headers.getSetCookie())
      outgoing.append("set-cookie", cookie);
    outgoing.set("cache-control", "no-store");
    outgoing.set("x-accel-buffering", "no");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: outgoing,
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "backend_unavailable",
          message: "暂时无法连接服务，请稍后重试",
        },
      },
      { status: 503 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
  proxy as HEAD,
};
