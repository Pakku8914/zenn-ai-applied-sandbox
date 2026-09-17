// 練習問題 2: code_verifier と code_challenge の対応づけを点検する。
import { challengeFor, createPkcePair } from "./rp-pkce.js";

/** RFC 7636 Appendix B に載っている検証用データ（仕様側が示している正解） */
const RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
const RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";

const BASE64URL_ONLY = /^[A-Za-z0-9\-._~]+$/;

export function buildPkceCheckReport(sampleCount = 100): string[] {
  const pairs = Array.from({ length: sampleCount }, () => createPkcePair());
  const verifiers = pairs.map((pair) => pair.codeVerifier);

  // 1 文字だけ変えた verifier からは、まったく違う challenge が出ることを確かめます
  const original = RFC_VERIFIER;
  const altered = `${original.slice(0, -1)}${original.endsWith("k") ? "K" : "k"}`;

  return [
    "=== PKCE の対応づけの点検 ===",
    `RFC 7636 の検証用データ: ${challengeFor(RFC_VERIFIER) === RFC_CHALLENGE ? "一致" : "不一致"}`,
    `${sampleCount} 組すべてで code_verifier が 43 文字: ${verifiers.every((v) => v.length === 43)}`,
    `${sampleCount} 組すべてで Base64URL の文字だけ: ${verifiers.every((v) => BASE64URL_ONLY.test(v))}`,
    `${sampleCount} 組すべてで code_challenge を再計算できる: ${pairs.every(
      (pair) => challengeFor(pair.codeVerifier) === pair.codeChallenge,
    )}`,
    `重複した code_verifier の数: ${verifiers.length - new Set(verifiers).size}`,
    `verifier を 1 文字変えると challenge も変わる: ${challengeFor(altered) !== RFC_CHALLENGE}`,
  ];
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q2-pkce-check"))) {
  for (const line of buildPkceCheckReport()) console.log(line);
}
