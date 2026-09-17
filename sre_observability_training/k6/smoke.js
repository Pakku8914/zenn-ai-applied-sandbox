// 短時間のスモーク負荷。SLO を踏む挙動が出ることの確認に使う。
// 実行: docker compose run --rm k6 run /scripts/smoke.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 5,
  duration: '20s',
  thresholds: {
    // 意図的に 5 回に 1 回失敗する設計なので、失敗率 25% 未満なら想定どおり
    http_req_failed: ['rate<0.25'],
    http_req_duration: ['p(95)<1500'],
  },
};

const TARGET = __ENV.TARGET || 'http://app:8000';

export default function () {
  const list = http.get(`${TARGET}/api/products`);
  check(list, { 'products 200': (r) => r.status === 200 });

  const checkout = http.post(`${TARGET}/api/checkout`);
  check(checkout, { 'checkout 応答あり': (r) => r.status === 200 || r.status === 500 });

  sleep(0.5);
}
