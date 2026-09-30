/**
 * 擬似的な外部タグ（計測タグや A/B テストのスニペットの代わり）。
 * 本物のタグは読み込まない（外部サイトへのアクセスを前提にしないため）。
 * 中身の処理の代わりに、決まった時間だけメインスレッドを占有する。
 * 教材用の再現コードなので、本番のコードでこのような待ち方をしてはいけない。
 */
export const TAG_BLOCKING_MS = 300;

export function runThirdPartyTag(): void {
  const end = performance.now() + TAG_BLOCKING_MS;
  while (performance.now() < end) {
    // 何もしない（メインスレッドを占有することだけが目的）
  }
}
