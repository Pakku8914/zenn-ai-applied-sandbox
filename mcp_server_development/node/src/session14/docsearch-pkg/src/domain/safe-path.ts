/**
 * 社内ドキュメント検索 ― パス検証（ドメイン層）
 *
 * docs://{+path} の path は外部入力です。テンプレートに一致したことは
 * 「形が合っている」だけで「安全である」ことを一切意味しません。
 *
 * このファイルは MCP を知りません（@modelcontextprotocol/sdk を import しない）。
 * 拒否理由を RejectReason という機械可読な値で返し、MCP のエラーへの翻訳は
 * 上位（create-server.ts）に任せます。
 */
import fs from "node:fs";
import path from "node:path";

/** 拒否理由。テストではこの値で検証する（文面を変えてもテストが壊れない） */
export type RejectReason =
  | "empty"
  | "invalid_encoding"
  | "control_character"
  | "too_long"
  | "drive_letter"
  | "backslash"
  | "absolute_path"
  | "parent_traversal"
  | "too_deep"
  | "invalid_segment"
  | "not_markdown"
  | "outside_root"
  | "symlink"
  | "not_found"
  | "not_file";

export type SafePath =
  | { readonly ok: true; readonly relativePath: string; readonly absolutePath: string }
  | { readonly ok: false; readonly reason: RejectReason };

export const MAX_PATH_LENGTH = 200;
/** 相対パスの区間数の上限（"guides/vpn-setup.md" は 2 区間） */
export const MAX_DEPTH = 3;
/** 区間に許す文字。先頭は英数字に限定してドットファイルを弾く */
export const SEGMENT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

const DRIVE_LETTER_PATTERN = /^[A-Za-z]:/;
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f]/;

/**
 * 拒否理由ごとの固定文面。
 *
 * 受け取った入力値とサーバー内部の絶対パスを**含めない**のが要点です。
 *   ① 入力を反射すると、攻撃者が仕込んだ文字列がログとモデルのコンテキストに載る
 *   ② 内部パスを返すと、ディレクトリ構成という情報を無料で渡すことになる
 * 代わりに「どうすれば直るか」を書きます（AI が自力で回復できるエラー文にする）。
 */
export const REJECT_MESSAGES: Record<RejectReason, string> = {
  empty: "path が空です。docs://onboarding.md のように指定してください。",
  invalid_encoding: "path のパーセントエンコードが不正です。",
  control_character: "path に使用できない制御文字が含まれています。",
  too_long: `path が長すぎます（${MAX_PATH_LENGTH} 文字以内で指定してください）。`,
  drive_letter: "path にドライブレターは使用できません。",
  backslash: "path の区切りには / を使用してください。",
  absolute_path: "path は公開ディレクトリからの相対パスで指定してください。",
  parent_traversal: "path に .. や . を含めることはできません。",
  too_deep: `path の階層は ${MAX_DEPTH} 段までです。`,
  invalid_segment:
    "path に使用できるのは半角英数字とピリオド・ハイフン・アンダースコアのみです。",
  not_markdown: "参照できるのは拡張子 .md のファイルだけです。",
  outside_root: "指定されたファイルは公開対象のディレクトリの外にあります。",
  symlink:
    "指定されたファイルはシンボリックリンクで公開対象の外を指しているため参照できません。",
  not_found:
    "指定されたファイルは見つかりません。resources/list で公開されている文書を確認してください。",
  not_file: "指定されたパスはファイルではありません。",
};

/**
 * 構文検査だけを行う（ファイルシステムに触らない）。
 *
 * 検査の順序には意味があります。入れ替えると拒否理由が変わります。
 *   - ドライブレターはバックスラッシュより先（"C:\\x" は両方に該当する）
 *   - .. の検査は区間数より先（"../../etc/passwd" は 4 区間ある）
 */
export function normalizeDocPath(
  raw: string,
): { ok: true; relativePath: string } | { ok: false; reason: RejectReason } {
  // ① デコードは 1 回だけ。2 回行うと %252f（%2f の二重エンコード）を通してしまう
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw.trim());
  } catch {
    // 壊れたパーセントエンコード（例: "%zz"）はここで落ちる
    return { ok: false, reason: "invalid_encoding" };
  }

  if (decoded.length === 0) {
    return { ok: false, reason: "empty" };
  }
  if (decoded.length > MAX_PATH_LENGTH) {
    return { ok: false, reason: "too_long" };
  }
  // ② NUL バイトによる拡張子偽装（"a.md%00.txt"）をここで落とす
  if (CONTROL_CHARACTER_PATTERN.test(decoded)) {
    return { ok: false, reason: "control_character" };
  }
  if (DRIVE_LETTER_PATTERN.test(decoded)) {
    return { ok: false, reason: "drive_letter" };
  }
  if (decoded.includes("\\")) {
    return { ok: false, reason: "backslash" };
  }
  if (decoded.startsWith("/")) {
    return { ok: false, reason: "absolute_path" };
  }

  const segments = decoded.split("/");
  // ③ .. と . は区間単位で判定する。文字列の includes("..") では
  //    "..data.md" のような正当な名前まで弾いてしまう
  if (segments.some((segment) => segment === "." || segment === "..")) {
    return { ok: false, reason: "parent_traversal" };
  }
  if (segments.length > MAX_DEPTH) {
    return { ok: false, reason: "too_deep" };
  }
  // ④ 許可リスト。空文字の区間（"a//b.md" や末尾の "/"）もここで落ちる
  if (segments.some((segment) => !SEGMENT_PATTERN.test(segment))) {
    return { ok: false, reason: "invalid_segment" };
  }
  const last = segments[segments.length - 1];
  if (last === undefined || !last.toLowerCase().endsWith(".md")) {
    return { ok: false, reason: "not_markdown" };
  }

  return { ok: true, relativePath: segments.join("/") };
}

/**
 * 構文検査 → 実パス確認まで行う。
 *
 * ⑤ 正規化後に公開ディレクトリ配下かを確認する（構文検査の取りこぼしへの二重の壁）
 * ⑥ realpath で実体を解決し、もう一度配下かを確認する（シンボリックリンク対策）
 */
export function resolveSafeDocPath(root: string, raw: string): SafePath {
  const normalized = normalizeDocPath(raw);
  if (!normalized.ok) {
    return normalized;
  }

  // 基準ディレクトリ側にも realpath を掛ける。
  // /tmp が環境によってシンボリックリンクの場合、掛けないと ⑥ で誤判定する
  const realRoot = realPathOrUndefined(root);
  if (realRoot === undefined) {
    return { ok: false, reason: "not_found" };
  }

  const candidate = path.resolve(realRoot, normalized.relativePath);
  if (!isInside(realRoot, candidate)) {
    return { ok: false, reason: "outside_root" };
  }

  const real = realPathOrUndefined(candidate);
  if (real === undefined) {
    return { ok: false, reason: "not_found" };
  }
  if (!isInside(realRoot, real)) {
    return { ok: false, reason: "symlink" };
  }
  if (!fs.statSync(real).isFile()) {
    return { ok: false, reason: "not_file" };
  }

  return { ok: true, relativePath: normalized.relativePath, absolutePath: real };
}

function realPathOrUndefined(target: string): string | undefined {
  try {
    return fs.realpathSync(target);
  } catch {
    // 存在しない・権限が無い・リンクが循環している、のいずれか
    return undefined;
  }
}

/**
 * child が parent の配下（parent 自身は含まない）かを判定する。
 *
 * startsWith を使わないのが要点です。parent が "/app/docs" のとき、
 * "/app/docs-secret/leak.md" は startsWith を満たしてしまいます。
 */
export function isInside(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}
