declare global {
  interface Window {
    /** ハイドレーションが終わって、最初の useEffect が走った時刻（performance.now()） */
    __s12HydratedAt?: number;
  }
}

/** クライアントコンポーネントの useEffect から呼ぶ。最初の1回だけ記録する */
export function markHydrated(): void {
  if (window.__s12HydratedAt === undefined) {
    window.__s12HydratedAt = performance.now();
  }
}
