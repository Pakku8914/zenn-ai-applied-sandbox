import { serve } from "@hono/node-server";
import { createWebApp } from "./web-app-session-login.js";
// COOKIE_SECURE=true を付けると Secure 付きの Cookie になる（HTTP では送られなくなるので比較用）
const app = await createWebApp({ cookieSecure: process.env["COOKIE_SECURE"] === "true" });
serve({ fetch: app.fetch, port: 3100 });
