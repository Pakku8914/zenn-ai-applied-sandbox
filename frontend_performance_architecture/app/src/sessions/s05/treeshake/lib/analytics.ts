declare global {
  var __s05Analytics: string | undefined;
}

// 最上位で外の世界（グローバル変数）を書き換えている＝副作用がある。
// バンドラーは「消すと動作が変わるかもしれない」と考え、何も import されていなくても残す。
globalThis.__s05Analytics = '[analytics] ready';

export function trackView(page: string): void {
  console.info(`[analytics] view ${page}`);
}
