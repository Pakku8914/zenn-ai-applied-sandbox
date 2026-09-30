import { judge, type Finding, type Placement } from '../depRules';

/**
 * 練習問題4：規則を1つ足した判定。
 * feature の内部のファイルが、自分の feature の公開窓口（index.ts）を import するのを禁止する。
 * index.ts はその内部ファイルを export しているので、放っておくと循環 import になる。
 */
export function judgeStrict(from: Placement, to: Placement): Finding | null {
  const base = judge(from, to);
  if (base) return base;
  const sameFeature = from.layer === 'feature' && to.layer === 'feature' && from.feature === to.feature;
  if (sameFeature && to.isPublic && !from.isPublic) {
    return {
      rule: 'self-public',
      message: `features/${from.feature ?? '?'} の内部から自分の公開窓口を import しています（循環 import の元）`,
    };
  }
  return null;
}
