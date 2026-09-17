/**
 * 気象観測データの生成とページネーション用ヘルパー
 *
 * 10 万件を固定シードから決定的に生成します。実行するたびに同じ値になるので、
 * 集計結果やページの中身が本書の記載と一致します。
 */

/** 観測レコード（内部表現）。気温と降水量は 0.1 単位の整数で保持します */
export type Observation = {
  id: string;
  stationId: string;
  observedAt: string;
  /** 気温（0.1℃ 単位の整数）。整数で持つと集計結果が言語をまたいで一致します */
  temperatureTenths: number;
  humidityPct: number;
  /** 降水量（0.1mm 単位の整数） */
  precipitationTenths: number;
};

/** 外部（クライアント）に見せる形。プロトコルに出る名前は camelCase で統一します */
export type PublicObservation = {
  id: string;
  stationId: string;
  observedAt: string;
  temperatureC: number;
  humidityPct: number;
  precipitationMm: number;
};

export const TOTAL_OBSERVATIONS = 100_000;
/** 集計を何チャンクに分けるか（= 進捗通知の回数） */
export const TOTAL_STEPS = 20;

const STATION_IDS = [
  "st-01", "st-02", "st-03", "st-04", "st-05",
  "st-06", "st-07", "st-08", "st-09", "st-10",
] as const;
const START_MS = Date.UTC(2026, 0, 1, 0, 0, 0);
const SEED = 20_260_805;

/**
 * 線形合同法（MINSTD）による疑似乱数。
 * 乗算が 2^53 を超えないため、JavaScript の Number でも Python の int でも
 * まったく同じ数列になります（2 言語で同じ集計結果を得るための工夫です）。
 */
function createRandom(seed: number): () => number {
  let state = seed % 2_147_483_647;
  if (state <= 0) state += 2_147_483_646;
  return () => {
    state = (state * 48_271) % 2_147_483_647;
    return state;
  };
}

let cache: Observation[] | undefined;

/** 10 万件を生成して返す（初回だけ生成し、以降はキャッシュを返す） */
export function getObservations(): Observation[] {
  if (cache !== undefined) return cache;

  const nextRandom = createRandom(SEED);
  const rows: Observation[] = [];
  for (let i = 0; i < TOTAL_OBSERVATIONS; i++) {
    const temperatureTenths = -50 + (nextRandom() % 451); // -5.0℃ 〜 40.0℃
    const humidityPct = 20 + (nextRandom() % 81); // 20% 〜 100%
    const precipitationTenths = nextRandom() % 61; // 0.0mm 〜 6.0mm
    rows.push({
      id: `obs-${String(i + 1).padStart(6, "0")}`,
      // tsconfig の noUncheckedIndexedAccess により添字アクセスは undefined を含むため
      // 非 null アサーションを付けています（範囲は剰余で保証済み）
      stationId: STATION_IDS[i % STATION_IDS.length]!,
      observedAt: new Date(START_MS + i * 60_000).toISOString(),
      temperatureTenths,
      humidityPct,
      precipitationTenths,
    });
  }
  cache = rows;
  return rows;
}

export function toPublic(row: Observation): PublicObservation {
  return {
    id: row.id,
    stationId: row.stationId,
    observedAt: row.observedAt,
    temperatureC: row.temperatureTenths / 10,
    humidityPct: row.humidityPct,
    precipitationMm: row.precipitationTenths / 10,
  };
}

// ---------------- ページネーション ----------------

/** オフセット方式（Bad 側の比較用）。offset 件を読み飛ばして limit 件返す */
export function paginateByOffset(
  rows: readonly Observation[],
  offset: number,
  limit: number,
): { items: Observation[]; nextOffset: number; hasMore: boolean } {
  const items = rows.slice(offset, offset + limit);
  return {
    items,
    nextOffset: offset + items.length,
    hasMore: offset + items.length < rows.length,
  };
}

/**
 * afterId より大きい最初の位置を二分探索で求める。
 * 「その ID を含む行が削除されていても正しい位置が出る」ことが要点です。
 */
export function findStartIndex(rows: readonly Observation[], afterId: string): number {
  let low = 0;
  let high = rows.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (rows[mid]!.id <= afterId) low = mid + 1;
    else high = mid;
  }
  return low;
}

/** キーセット方式。「最後に返した ID の次から」limit 件返す */
export function paginateByKeyset(
  rows: readonly Observation[],
  afterId: string | undefined,
  limit: number,
): { items: Observation[]; lastId: string | undefined; hasMore: boolean } {
  const start = afterId === undefined ? 0 : findStartIndex(rows, afterId);
  const items = rows.slice(start, start + limit);
  return {
    items,
    lastId: items.at(-1)?.id,
    hasMore: start + items.length < rows.length,
  };
}

/** カーソルを不透明な文字列にする（クライアントに中身を解釈させない） */
export function encodeCursor(afterId: string): string {
  const payload = JSON.stringify({ v: 1, afterId });
  return Buffer.from(payload, "utf8").toString("base64url");
}

/** カーソルを復号する。壊れていれば例外を投げる */
export function decodeCursor(cursor: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
  } catch {
    throw new Error("cursor を復号できません");
  }
  if (typeof parsed !== "object" || parsed === null) throw new Error("cursor の形式が不正です");
  const { v, afterId } = parsed as { v?: unknown; afterId?: unknown };
  // バージョンを埋めておくと、後でカーソルの構造を変えたときに古いカーソルを弾けます
  if (v !== 1 || typeof afterId !== "string") throw new Error("cursor のバージョンが不正です");
  return afterId;
}

// ---------------- 集計 ----------------

export type StationAccumulator = {
  count: number;
  sumTenths: number;
  maxTenths: number;
  precipTenths: number;
};

export type StationSummary = {
  stationId: string;
  count: number;
  avgTemperatureC: number;
  maxTemperatureC: number;
  totalPrecipitationMm: number;
};

/** チャンク 1 つ分を観測所ごとに足し込む */
export function accumulate(
  acc: Map<string, StationAccumulator>,
  rows: readonly Observation[],
): void {
  for (const row of rows) {
    const current = acc.get(row.stationId) ?? {
      count: 0,
      sumTenths: 0,
      maxTenths: Number.NEGATIVE_INFINITY,
      precipTenths: 0,
    };
    current.count += 1;
    current.sumTenths += row.temperatureTenths;
    current.maxTenths = Math.max(current.maxTenths, row.temperatureTenths);
    current.precipTenths += row.precipitationTenths;
    acc.set(row.stationId, current);
  }
}

export function summarize(acc: Map<string, StationAccumulator>): StationSummary[] {
  return [...acc.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([stationId, value]) => ({
      stationId,
      count: value.count,
      // 整数の切り捨て除算だけで平均を出しています。
      // 浮動小数の丸めは言語ごとに規則が違うため、値を一致させたいときは整数演算に寄せます
      avgTemperatureC: Math.floor((value.sumTenths * 10) / value.count) / 100,
      maxTemperatureC: value.maxTenths / 10,
      totalPrecipitationMm: value.precipTenths / 10,
    }));
}
