/** 問題6：JavaScript で付ける動きは CSS のメディアクエリが効かないので、設定を読んで切り替える */
export function scrollBehaviorFor(prefersReducedMotion: boolean): ScrollBehavior {
  return prefersReducedMotion ? 'auto' : 'smooth';
}

/** ブラウザで使うときの読み取り。テスト（環境 node）では scrollBehaviorFor だけを検査する */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
