import { onCLS, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';

export type CollectedMetric = {
  name: string;
  value: number;
  rating: Metric['rating'];
};

declare global {
  interface Window {
    __webVitals?: CollectedMetric[];
  }
}

/**
 * Core Web Vitals を window.__webVitals に蓄積する。
 * 本書では「ブラウザが実際に報告した値」だけを根拠にするため、自作の計測は行わない。
 */
export function reportWebVitals(): void {
  window.__webVitals = [];

  const push = (metric: Metric): void => {
    window.__webVitals?.push({
      name: metric.name,
      value: Math.round(metric.value * 1000) / 1000,
      rating: metric.rating,
    });
  };

  // reportAllChanges を付けないと、LCP と CLS は「もう変わらない」と確定するまで
  // 報告されない。確定の契機は requestIdleCallback 相当なので、自動計測では
  // いつまでも値が取れないことがある。変化するたび受け取り、最後の値を確定値として使う。
  onLCP(push, { reportAllChanges: true });
  onCLS(push, { reportAllChanges: true });
  onINP(push, { reportAllChanges: true });
  onTTFB(push);
}
