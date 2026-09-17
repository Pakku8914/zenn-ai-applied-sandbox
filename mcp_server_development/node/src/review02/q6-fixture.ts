  /**
   * 問題6 の実験用ファイル置き場と、検証を省いた読み取り関数（攻撃対象）。
   *
   * 置き場をコンテナの /tmp 配下にしているのは、ホスト側のリポジトリを汚さないためです。
   * コンテナを作り直すと消えるので、その場合は q6-setup.ts を再実行してください。
   */
  import fs from "node:fs/promises";
  import path from "node:path";

  export const NOTICE_DIR = "/tmp/review02-notices";

  /** 公開してよいファイル（補完の候補にも使う）。symlink の staff-only.md は入れない */
  export const PUBLIC_FILES = ["fire-drill.md", "parking.md", "wifi-guest.md"] as const;

  const FILE_BODIES: Record<(typeof PUBLIC_FILES)[number], string> = {
    "fire-drill.md": [
      "# 防災訓練の実施について",
      "",
      "9 月 1 日 10 時から全館で防災訓練を行います。",
      "避難経路は各フロアの掲示を確認してください。",
    ].join("\n"),
    "parking.md": [
      "# 駐輪場の利用登録",
      "",
      "駐輪場を使う方は総務ポータルから登録してください。",
      "登録シールは受付で配布します。",
    ].join("\n"),
    "wifi-guest.md": [
      "# 来客用 Wi-Fi の利用手順",
      "",
      "来客用 Wi-Fi のパスワードは受付で発行します。",
      "社内ネットワークへは接続できません。",
    ].join("\n"),
  };

  /** 実験用のファイルとシンボリックリンクを作り直す（何度実行してもよい） */
  export async function createFixture(): Promise<string[]> {
    await fs.rm(NOTICE_DIR, { recursive: true, force: true });
    await fs.mkdir(NOTICE_DIR, { recursive: true });

    const created: string[] = [];
    for (const name of PUBLIC_FILES) {
      await fs.writeFile(path.join(NOTICE_DIR, name), `${FILE_BODIES[name]}\n`, "utf8");
      created.push(name);
    }

    // 「許可リストは通るが、参照先が外を向いている」ファイルを 1 つ置く
    await fs.symlink("/etc/passwd", path.join(NOTICE_DIR, "staff-only.md"));
    created.push("staff-only.md -> /etc/passwd");
    return created;
  }

  /**
   * ❌ 検証を省いた読み取り（攻撃対象）。3 つの誤りが入っています。
   *   ① パーセントデコードを 2 回行っている
   *   ② path.resolve が「..」と絶対パスをそのまま解釈する
   *   ③ 許可リストも参照先の検査も無い
   */
  export async function badResolveNoticeFile(
    raw: string,
  ): Promise<{ filePath: string; text: string }> {
    const decoded = decodeURIComponent(decodeURIComponent(raw));
    const filePath = path.resolve(NOTICE_DIR, decoded);
    const text = await fs.readFile(filePath, "utf8");
    return { filePath, text };
  }
