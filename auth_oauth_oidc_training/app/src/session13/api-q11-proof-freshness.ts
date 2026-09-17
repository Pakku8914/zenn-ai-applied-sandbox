// セッション 13（後半）問題 1: proof の「鮮度」（iat）と「使い捨て」（jti）だけを取り出して判定します。
// verifyDpopProof() が確かめる 5 観点のうち、時間に関わる 2 つを単体で扱います。
import { PROOF_IAT_WINDOW, ProofReplayGuard } from "./api-service-dpop.js";

/** 未来に寄りすぎた proof も拒みます（時計のずれか、作りだめの兆候） */
export type FreshnessVerdict = "fresh" | "too_old" | "too_new" | "no_iat";

export function checkFreshness(iat: unknown, now: number, window: number = PROOF_IAT_WINDOW): FreshnessVerdict {
  // 数値でなければ引き算の前に返します（undefined との演算は NaN になり比較が全部 false になる）
  if (typeof iat !== "number") return "no_iat";
  const drift = now - iat;
  if (drift > window) return "too_old";
  if (-drift > window) return "too_new";
  return "fresh";
}

export type JtiVerdict = "first_time" | "replayed";

/**
 * 同じ jti を 2 回 → 別の jti → 窓の 2 倍を過ぎたあとに最初の jti、の 4 回。
 * 4 回目が再び通るのは、その頃の proof が iat の判定（too_old）で先に落ちるからです。
 */
export function jtiSequence(now: number, window: number = PROOF_IAT_WINDOW): readonly JtiVerdict[] {
  const guard = new ProofReplayGuard(window);
  const at = (jti: string, t: number): JtiVerdict => (guard.accept(jti, t) ? "first_time" : "replayed");
  return [at("proof-a", now), at("proof-a", now), at("proof-b", now), at("proof-a", now + window * 2 + 1)];
}
