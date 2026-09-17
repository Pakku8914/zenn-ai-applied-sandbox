// デプロイ先が「このコンテナは仕事を受けられるか」を判断するための状態（セッション28）。
//
// ロードバランサやコンテナの管理基盤は、決まった URL を定期的に叩いて
// 200 が返るかどうかだけを見る。だから「何が悪いか」を人が読むための本文と、
// 「受けられるか」を機械が読むためのステータスコードを分けて作る。
//
// この判断はデータベースにも Prisma にも依存させない。調べた結果（HealthProbe）を
// 引数で受け取る純粋関数にしておけば、全パターンをテストで確かめられる。
// セッション26 で作った /api/health に組み込むのは復習04と最終プロジェクトで扱う。

/** 調べた結果。判別タグは本書共通の kind（セッション12で決めた規約） */
export type HealthProbe =
  | { kind: 'ready'; appliedMigrationCount: number }
  | { kind: 'database-unreachable' }
  | { kind: 'migrations-pending'; pending: readonly string[] }
  | { kind: 'config-invalid'; missing: readonly string[] };

/** 返す HTTP ステータス。受けられるなら 200、受けられないなら 503 */
export type HealthStatusCode = 200 | 503;

export const HEALTH_OK: HealthStatusCode = 200;
export const HEALTH_UNAVAILABLE: HealthStatusCode = 503;

/**
 * 状態から HTTP ステータスを決める。
 * 「準備できている」以外はすべて 503（Service Unavailable）にする。
 * 500 ではなく 503 にするのは「今は無理だが、あとで直るかもしれない」を表すため。
 */
export function toHealthStatus(probe: HealthProbe): HealthStatusCode {
  return probe.kind === 'ready' ? HEALTH_OK : HEALTH_UNAVAILABLE;
}

export type HealthBody = {
  status: 'ok' | 'unavailable';
  /** 機械が読める理由。文言を変えると監視の設定が壊れるので固定する */
  reason: 'ready' | 'database_unreachable' | 'migrations_pending' | 'config_invalid';
  /** 人が読むための手がかり。名前だけを入れ、値は絶対に入れない */
  detail: string[];
};

/**
 * 応答の本文を作る。
 * 接続文字列やトークンの「値」を入れてはいけない。ヘルスチェックの応答は
 * たいてい認証なしで公開されるため、入れた瞬間に漏洩になる。
 */
export function buildHealthBody(probe: HealthProbe): HealthBody {
  switch (probe.kind) {
    case 'ready':
      return { status: 'ok', reason: 'ready', detail: [] };
    case 'database-unreachable':
      // 接続先のホスト名やパスワードは出さない。出しても直せる人は増えない
      return { status: 'unavailable', reason: 'database_unreachable', detail: [] };
    case 'migrations-pending':
      return {
        status: 'unavailable',
        reason: 'migrations_pending',
        detail: [...probe.pending],
      };
    case 'config-invalid':
      return { status: 'unavailable', reason: 'config_invalid', detail: [...probe.missing] };
    default: {
      // 状態を増やしたらここで型エラーになる（セッション12の網羅性チェック）
      const unexpected: never = probe;

      return unexpected;
    }
  }
}
