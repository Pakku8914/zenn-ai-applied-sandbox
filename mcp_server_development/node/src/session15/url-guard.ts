/**
 * 外向き HTTP リクエストの検証（SSRF 対策）
 *
 * 名前解決を関数で受け取るのが要点です。①テストでネットワークに出ない
 * ②「解決した IP に接続する」実装へ差し替えられる、の 2 つのためです。
 *
 * 重要な限界（実装ではなく運用で埋める部分）:
 *   - リダイレクトは追跡しない。追う場合は毎ホップこの関数を通し直す
 *   - 検証から接続までの間に解決結果が変わりうる（DNS リバインディング）。
 *     本番では「検証した IP に直接接続し、Host ヘッダーに元のホスト名を入れる」
 */
import { lookup } from "node:dns/promises";

export type UrlRejectReason =
  | "invalid_url"
  | "scheme_not_allowed"
  | "userinfo_present"
  | "port_not_allowed"
  | "host_not_allowed"
  | "ip_literal_blocked"
  | "resolved_to_blocked_ip"
  | "dns_failure";

export type UrlCheck =
  | { readonly ok: true; readonly url: URL; readonly addresses: readonly string[] }
  | { readonly ok: false; readonly reason: UrlRejectReason };

export type Resolver = (hostname: string) => Promise<readonly string[]>;

export type UrlGuardOptions = {
  /** 許可するホスト名（完全一致・小文字で列挙する） */
  readonly allowedHosts: readonly string[];
  readonly allowedPorts?: readonly number[];
  readonly resolve?: Resolver;
};

export const DEFAULT_ALLOWED_PORTS: readonly number[] = [80, 443];

export const defaultResolver: Resolver = async (hostname) => {
  const results = await lookup(hostname, { all: true });
  return results.map((entry) => entry.address);
};

export async function checkOutboundUrl(
  raw: string,
  options: UrlGuardOptions,
): Promise<UrlCheck> {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, reason: "invalid_url" };
  }

  // ① スキームの許可リスト。file: や gopher: を通すと別の攻撃面が開く
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: "scheme_not_allowed" };
  }
  // ② URL に埋め込まれた認証情報は拒否（そのまま例外やログに出る）
  if (url.username !== "" || url.password !== "") {
    return { ok: false, reason: "userinfo_present" };
  }
  // ③ ポートの許可リスト
  const allowedPorts = options.allowedPorts ?? DEFAULT_ALLOWED_PORTS;
  const port =
    url.port === "" ? (url.protocol === "https:" ? 443 : 80) : Number.parseInt(url.port, 10);
  if (!allowedPorts.includes(port)) {
    return { ok: false, reason: "port_not_allowed" };
  }
  // ④ ホスト部が IP リテラルなら拒否（許可リストはホスト名で運用する）
  if (isIpLiteral(url.hostname)) {
    return { ok: false, reason: "ip_literal_blocked" };
  }
  // ⑤ ホスト名の許可リスト。前方一致にすると docs.example.com.evil.test が通る
  if (!options.allowedHosts.includes(url.hostname.toLowerCase())) {
    return { ok: false, reason: "host_not_allowed" };
  }

  // ⑥ 名前解決の結果を検査する。ここまでは「文字列の検査」にすぎない
  const resolve = options.resolve ?? defaultResolver;
  let addresses: readonly string[];
  try {
    addresses = await resolve(url.hostname);
  } catch {
    return { ok: false, reason: "dns_failure" };
  }
  if (addresses.length === 0) {
    return { ok: false, reason: "dns_failure" };
  }
  // 1 つでも禁止帯にあれば拒否する（片方だけ内部を指すラウンドロビンがある）
  if (addresses.some((address) => isBlockedAddress(address))) {
    return { ok: false, reason: "resolved_to_blocked_ip" };
  }

  return { ok: true, url, addresses };
}

/** ホスト部が IP アドレスリテラルか。判定は広めに（安全側に）倒す */
export function isIpLiteral(hostname: string): boolean {
  // new URL() は IPv6 の角括弧を外すので、コロンがあれば IPv6 リテラル
  if (hostname.includes(":")) {
    return true;
  }
  // 10 進・8 進（010.0.0.1）・16 進（0x7f000001）の表記をまとめて拾う
  return /^[0-9.]+$/.test(hostname) || /^0[xX][0-9a-fA-F]+$/.test(hostname);
}

/** 接続してはいけないアドレスか */
export function isBlockedAddress(address: string): boolean {
  const normalized = address.toLowerCase().trim();
  // IPv4 射影アドレス（::ffff:127.0.0.1）は IPv6 の形をした IPv4
  const mapped = normalized.startsWith("::ffff:")
    ? normalized.slice("::ffff:".length)
    : normalized;
  if (/^[0-9.]+$/.test(mapped)) {
    return isBlockedIpv4(mapped);
  }
  return isBlockedIpv6(mapped);
}

function isBlockedIpv4(address: string): boolean {
  const parts = address.split(".").map((part) => Number.parseInt(part, 10));
  if (
    parts.length !== 4 ||
    parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)
  ) {
    // 解釈できない表記は安全側に倒して拒否する
    return true;
  }
  const [first = 0, second = 0] = parts;
  if (first === 0) return true; // 0.0.0.0/8
  if (first === 10) return true; // プライベート
  if (first === 127) return true; // ループバック
  if (first === 169 && second === 254) return true; // リンクローカル（メタデータ）
  if (first === 172 && second >= 16 && second <= 31) return true; // プライベート
  if (first === 192 && second === 168) return true; // プライベート
  if (first === 100 && second >= 64 && second <= 127) return true; // CGNAT
  return false;
}

function isBlockedIpv6(address: string): boolean {
  if (address === "::" || address === "::1") return true;
  const head = address.split(":")[0] ?? "";
  // fc00::/7（ユニークローカル）
  if (head.startsWith("fc") || head.startsWith("fd")) return true;
  // fe80::/10（リンクローカル）
  if (/^fe[89ab]/.test(head)) return true;
  return false;
}
