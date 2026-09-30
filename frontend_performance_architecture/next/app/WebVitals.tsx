'use client';

import { useEffect } from 'react';
import { onCLS, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';

type CollectedMetric = { name: string; value: number; rating: Metric['rating'] };

declare global {
  interface Window {
    __webVitals?: CollectedMetric[];
  }
}

/**
 * SPA 側の app/src/vitals.ts と同じ形で window.__webVitals に貯める（計測側との契約）。
 * LCP・CLS は buffered な observer で取るので、ハイドレーション後に登録しても取りこぼさない。
 */
export function WebVitals(): null {
  useEffect(() => {
    if (window.__webVitals) return;
    window.__webVitals = [];
    const push = (metric: Metric): void => {
      window.__webVitals?.push({
        name: metric.name,
        value: Math.round(metric.value * 1000) / 1000,
        rating: metric.rating,
      });
    };
    onLCP(push, { reportAllChanges: true });
    onCLS(push, { reportAllChanges: true });
    onINP(push, { reportAllChanges: true });
    onTTFB(push);
  }, []);
  return null;
}
