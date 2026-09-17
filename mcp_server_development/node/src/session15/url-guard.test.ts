import { describe, expect, it } from "vitest";

import { checkOutboundUrl, isBlockedAddress, isIpLiteral } from "./url-guard.js";

/** ネットワークに出ないスタブ。ホスト名 -> アドレスの対応表 */
const TABLE: Record<string, readonly string[]> = {
  "docs.example.com": ["93.184.216.34"],
  "evil.example.com": ["169.254.169.254"],
  "mixed.example.com": ["93.184.216.34", "10.0.0.5"],
  "broken.example.com": [],
};

const resolve = async (hostname: string): Promise<readonly string[]> => {
  const found = TABLE[hostname];
  if (found === undefined) {
    throw new Error("NXDOMAIN");
  }
  return found;
};

const options = {
  allowedHosts: ["docs.example.com", "evil.example.com", "mixed.example.com", "broken.example.com"],
  resolve,
};

describe("checkOutboundUrl", () => {
  it("許可ホスト・公開 IP なら通す", async () => {
    const result = await checkOutboundUrl("https://docs.example.com/a", options);
    expect(result.ok).toBe(true);
    if (result.ok) {
      // URL インスタンスを toEqual で比較しない（プロパティが getter なので比較が甘くなる）
      expect(result.url.hostname).toBe("docs.example.com");
      expect(result.addresses).toEqual(["93.184.216.34"]);
    }
  });

  it("名前解決がメタデータエンドポイントを指したら拒否する", async () => {
    const result = await checkOutboundUrl("https://evil.example.com/", options);
    expect(result).toEqual({ ok: false, reason: "resolved_to_blocked_ip" });
  });

  it("複数アドレスのうち 1 つでも禁止帯なら拒否する", async () => {
    const result = await checkOutboundUrl("https://mixed.example.com/", options);
    expect(result).toEqual({ ok: false, reason: "resolved_to_blocked_ip" });
  });

  it.each([
    ["file:///etc/passwd", "scheme_not_allowed"],
    ["https://user:pw@docs.example.com/", "userinfo_present"],
    ["https://docs.example.com:8443/", "port_not_allowed"],
    ["http://127.0.0.1:80/", "ip_literal_blocked"],
    ["http://[::1]/", "ip_literal_blocked"],
    ["https://other.example.com/", "host_not_allowed"],
    ["https://broken.example.com/", "dns_failure"],
    ["not a url", "invalid_url"],
  ])("%s は %s で拒否される", async (raw, reason) => {
    const result = await checkOutboundUrl(raw, options);
    expect(result).toEqual({ ok: false, reason });
  });
});

describe("isIpLiteral", () => {
  it.each(["127.0.0.1", "10.0.0.5", "::1", "0x7f000001", "010.0.0.1"])(
    "%s は IP リテラル",
    (hostname) => {
      expect(isIpLiteral(hostname)).toBe(true);
    },
  );

  it("ホスト名は IP リテラルではない", () => {
    expect(isIpLiteral("docs.example.com")).toBe(false);
  });
});

describe("isBlockedAddress", () => {
  it.each([
    "127.0.0.1",
    "0.0.0.0",
    "10.1.2.3",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "::1",
    "::",
    "fd00::1",
    "fe80::1",
    "::ffff:127.0.0.1",
    "999.1.1.1",
  ])("%s は禁止帯", (address) => {
    expect(isBlockedAddress(address)).toBe(true);
  });

  it.each(["93.184.216.34", "8.8.8.8", "172.32.0.1", "2606:4700::1111"])(
    "%s は許可",
    (address) => {
      expect(isBlockedAddress(address)).toBe(false);
    },
  );
});
