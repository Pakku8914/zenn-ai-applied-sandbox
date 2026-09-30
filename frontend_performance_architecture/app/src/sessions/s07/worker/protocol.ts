/** メインスレッドと Worker の間でやり取りするメッセージの型（両側で同じものを import する）。 */
export type PointsRequest = { kind: 'build' };
export type PointsResponse = { kind: 'done'; points: number[] };
