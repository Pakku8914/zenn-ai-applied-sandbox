declare global {
  interface Window {
    /** S09：コンポーネントごとの再レンダリング回数（本番ビルドでは Profiler の onRender が呼ばれないため手で数える） */
    __s09RenderCount?: Record<string, number>;
  }
}

/** コンポーネント本体の先頭で呼び、再レンダリングの回数を数える */
export function countRender(name: string): void {
  // vitest（node）や renderToString では window が無いので数えない
  if (typeof window === 'undefined') return;
  const counts = (window.__s09RenderCount ??= {});
  counts[name] = (counts[name] ?? 0) + 1;
}
