/**
 * 再レンダリング回数の手動カウンタ。コンポーネント本体の先頭で countRender('row') のように呼ぶ。
 *
 * <Profiler> の onRender は本番ビルドでは呼ばれない（profiling ビルドが必要）ため、
 * 本番ビルドを計測する本書では、関数が実行された回数をこのカウンタで数える。
 * 描画中の副作用は本来避けるべきもので、これは計測のためだけの仕掛け。製品コードには残さない。
 */
export type RenderCounts = Record<string, number>;

declare global {
  // ブラウザでは window.__s08RenderCount として Playwright から読める
  var __s08RenderCount: RenderCounts | undefined;
}

export function countRender(name: string): void {
  const counts = (globalThis.__s08RenderCount ??= {});
  counts[name] = (counts[name] ?? 0) + 1;
}

export function readRenderCount(name: string): number {
  return globalThis.__s08RenderCount?.[name] ?? 0;
}

export function resetRenderCount(): void {
  globalThis.__s08RenderCount = {};
}
