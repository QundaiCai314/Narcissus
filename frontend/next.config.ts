import type { NextConfig } from "next";
import { createHash } from "node:crypto";
const checkoutScriptHash = createHash("sha256").update("document.forms[0].submit();").digest("base64");
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
          },
        ],
      },
      {
        source: "/api/docs",
        headers: [
          {
            key: "Content-Security-Policy",
            value:
              "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'self'",
          },
        ],
      },
      {
        // Next config headers take precedence over proxy response headers.
        // Allow only the official gateways and exact SDK auto-submit script here.
        source: "/api/billing/orders/:id/pay",
        headers: [
          { key: "Content-Security-Policy", value: `default-src 'none'; form-action https://openapi-sandbox.dl.alipaydev.com https://openapi.alipay.com; script-src 'sha256-${checkoutScriptHash}'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'` },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};
export default config;
