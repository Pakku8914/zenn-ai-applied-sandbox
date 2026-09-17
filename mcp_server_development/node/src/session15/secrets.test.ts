import { inspect } from "node:util";

import { describe, expect, it } from "vitest";

import { REDACTED, Secret, SecretConfigError, loadSecrets, redactSecrets } from "./secrets.js";

/** 架空のトークン。本物を書かない（テストコードはリポジトリと CI ログに残る） */
const FAKE_TOKEN = "ghp_0123456789abcdefghijABCDEF";
const FAKE_PEPPER = "0123456789abcdef";

describe("Secret ―― 文字列化の 4 経路", () => {
  const secret = new Secret(FAKE_TOKEN);

  it("テンプレート文字列で漏れない", () => {
    expect(`token=${secret}`).toBe(`token=${REDACTED}`);
  });

  it("JSON 化で漏れない", () => {
    expect(JSON.stringify({ token: secret })).toBe(`{"token":"${REDACTED}"}`);
  });

  it("util.inspect（console.log の経路）で漏れない", () => {
    expect(inspect({ token: secret })).not.toContain(FAKE_TOKEN);
  });

  it("reveal() でだけ取り出せる", () => {
    expect(secret.reveal()).toBe(FAKE_TOKEN);
    expect(secret.length).toBe(FAKE_TOKEN.length);
  });
});

describe("loadSecrets ―― 起動時検査", () => {
  it("必須が揃っていれば読み込める", () => {
    const secrets = loadSecrets({ AUDIT_LOG_PEPPER: FAKE_PEPPER });
    expect(secrets.auditPepper.reveal()).toBe(FAKE_PEPPER);
    expect(secrets.upstreamToken).toBeUndefined();
  });

  it("必須が無ければ起動時に落ちる。文面に変数名は出すが値は出さない", () => {
    expect(() => loadSecrets({})).toThrow(SecretConfigError);
    expect(() => loadSecrets({})).toThrow(/AUDIT_LOG_PEPPER/);
  });

  it("空文字・空白だけは未設定として扱う", () => {
    expect(() => loadSecrets({ AUDIT_LOG_PEPPER: "   " })).toThrow(SecretConfigError);
  });

  it("短すぎる値は拒否する", () => {
    expect(() => loadSecrets({ AUDIT_LOG_PEPPER: "short" })).toThrow(/16 文字以上/);
  });

  it("任意の秘密は設定されていれば読み込む", () => {
    const secrets = loadSecrets({
      AUDIT_LOG_PEPPER: FAKE_PEPPER,
      UPSTREAM_API_TOKEN: FAKE_TOKEN,
    });
    expect(secrets.upstreamToken?.reveal()).toBe(FAKE_TOKEN);
  });
});

describe("redactSecrets ―― エラーメッセージの出口", () => {
  it("既知の秘密値を消す", () => {
    const message = `POST https://api.example.com/v1?token=${FAKE_TOKEN} が失敗しました`;
    const redacted = redactSecrets(message, [new Secret(FAKE_TOKEN)]);
    expect(redacted).not.toContain(FAKE_TOKEN);
    expect(redacted).toContain(REDACTED);
  });

  it("短い値は置換しない（無関係な文字列を壊さないため）", () => {
    expect(redactSecrets("abc def", [new Secret("abc")])).toBe("abc def");
  });
});
