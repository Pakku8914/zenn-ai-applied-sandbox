/**
 * 横断復習2 問題6 ― 検証つきのファイル解決
 *
 * 4 段構えで守ります。1 つでも抜けると読めてしまいます。
 *   ① パーセントデコードは 1 回だけ（%252f のような二重エンコードを通さない）
 *   ② 許可リスト（^[a-z0-9][a-z0-9-]{0,39}\.md$）で「..」「/」「%」を含む名前を落とす
 *   ③ realpath で実体を解決し、公開ディレクトリ配下かを判定（シンボリックリンク対策）
 *   ④ 通常ファイル以外（ディレクトリなど）を拒否
 *
 * 例外を投げずに結果を返すのは、呼び出し側（リソースのハンドラ）が
 * 拒否の理由を選んでエラー文を組み立てられるようにするためです。
 */
import fs from "node:fs/promises";
import path from "node:path";

import { NOTICE_DIR } from "./q6-fixture.js";

const FILE_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,39}\.md$/;

export type ResolveResult = { ok: true; realPath: string } | { ok: false; reason: string };

export async function resolveNoticeFile(raw: string): Promise<ResolveResult> {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // 壊れたパーセントエンコード（例: "%zz"）
    return { ok: false, reason: "パーセントエンコードが壊れています" };
  }

  // 許可リストは「通す形」を書く方式にする。禁止文字の列挙（ブラックリスト）は必ず漏れる
  if (!FILE_NAME_PATTERN.test(decoded)) {
    return { ok: false, reason: "許可されていない名前です" };
  }

  const realDir = await fs.realpath(NOTICE_DIR);
  const candidate = path.join(realDir, decoded);

  let realPath: string;
  try {
    // 実体（シンボリックリンクを解決した先）を求める
    realPath = await fs.realpath(candidate);
  } catch {
    return { ok: false, reason: "お知らせが見つかりません" };
  }

  // 実体が公開ディレクトリの外を向いていたら拒否する。
  // 許可リストを通った名前でも、リンク先は自由に変えられる
  if (!realPath.startsWith(realDir + path.sep)) {
    return { ok: false, reason: "参照先が公開ディレクトリの外です" };
  }

  const stats = await fs.stat(realPath);
  if (!stats.isFile()) {
    return { ok: false, reason: "通常のファイルではありません" };
  }

  return { ok: true, realPath };
}
