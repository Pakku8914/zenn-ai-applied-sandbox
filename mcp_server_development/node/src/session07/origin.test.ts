/**
 * Origin / Host 検証のテスト
 *
 *   docker compose exec node npx vitest run src/session07
 *
 * 検証ロジックが HTTP から独立している（引数はヘッダーの辞書だけ）ので、
 * サーバーを起動せずにテストできます。これはドメイン層を切り出したときと同じ効果です。
 */
import { describe, expect, it } from "vitest";

import { createTrustPolicy, resolveTrustPolicy, verifyRequestTrust } from "./origin.js";

const policy = createTrustPolicy({
  allowedOrigins: ["http://127.0.0.1:6274"],
  allowedHosts: ["127.0.0.1:3939"],
});

describe("verifyRequestTrust", () => {
  it("許可された Origin は通る", () => {
    const result = verifyRequestTrust(
      { origin: "http://127.0.0.1:6274", host: "127.0.0.1:3939" },
      policy,
    );
    expect(result.ok).toBe(true);
  });

  it("未知の Origin は origin_not_allowed で拒否する", () => {
    const result = verifyRequestTrust(
      { origin: "https://evil.example", host: "127.0.0.1:3939" },
      policy,
    );
    expect(result).toMatchObject({ ok: false, reason: "origin_not_allowed" });
  });

  it("Origin が無いリクエストは通す（ブラウザ発ではないため）", () => {
    const result = verifyRequestTrust({ host: "127.0.0.1:3939" }, policy);
    expect(result.ok).toBe(true);
  });

  it("未知の Host は host_not_allowed で拒否する", () => {
    const result = verifyRequestTrust({ host: "evil.example:3939" }, policy);
    expect(result).toMatchObject({ ok: false, reason: "host_not_allowed" });
  });

  it("enabled: false ではすべて通る（実験用の抜け道）", () => {
    const disabled = createTrustPolicy({ enabled: false });
    const result = verifyRequestTrust({ origin: "https://evil.example" }, disabled);
    expect(result.ok).toBe(true);
  });

  it("拒否メッセージに入力値を含めない", () => {
    const result = verifyRequestTrust({ origin: "https://evil.example" }, policy);
    // 情報漏えいとログインジェクションを避けるため、入力はメッセージに載せない
    expect(result.ok ? "" : result.detail).not.toContain("evil.example");
  });
});

describe("resolveTrustPolicy", () => {
  it("環境変数から許可リストを組み立てる", () => {
    const resolved = resolveTrustPolicy(
      { MCP_ALLOWED_ORIGINS: "http://a.example, http://b.example" },
      3939,
    );
    expect(resolved.allowedOrigins).toEqual(["http://a.example", "http://b.example"]);
    expect(resolved.allowedHosts).toEqual(["127.0.0.1:3939", "localhost:3939"]);
    expect(resolved.enabled).toBe(true);
  });

  it("MCP_TRUST_CHECK=off のときだけ無効になる", () => {
    expect(resolveTrustPolicy({ MCP_TRUST_CHECK: "off" }, 3939).enabled).toBe(false);
    expect(resolveTrustPolicy({ MCP_TRUST_CHECK: "on" }, 3939).enabled).toBe(true);
    expect(resolveTrustPolicy({}, 3939).enabled).toBe(true);
  });
});
