  /**
   * 実験用ファイル置き場を作る。
   *
   *   docker compose exec node npx tsx src/review02/q6-setup.ts
   *
   * これはサーバーではなく手元のスクリプトなので console.log を使ってかまいません。
   */
  import { NOTICE_DIR, createFixture } from "./q6-fixture.js";

  const created = await createFixture();
  console.log(`作成先: ${NOTICE_DIR}`);
  for (const item of created) {
    console.log(`- ${item}`);
  }
  console.log("この置き場はコンテナの /tmp 配下です。コンテナを作り直したら再実行してください");
