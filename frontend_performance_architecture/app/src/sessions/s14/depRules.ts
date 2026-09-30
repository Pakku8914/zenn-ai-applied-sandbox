/**
 * S14：依存ルールの判定（純粋関数だけ。ファイルの読み込みは verify/session14/check-deps.ts が行う）。
 * Node が型を取り除いて直接実行できるよう、enum など型除去できない構文と import は使わない。
 */

export type Layer = 'app' | 'feature' | 'shared-ui' | 'shared-lib';

export type Placement = {
  layer: Layer;
  /** layer が feature のときだけ入る（catalog・cart など） */
  feature?: string;
  /** feature の公開窓口（直下の index.ts / index.tsx）かどうか */
  isPublic: boolean;
};

export type RuleId = 'unplaced' | 'layer' | 'cross-feature' | 'public-api';

/** 判定の結果。rule は RuleId 以外の独自規則も入れられるよう string にしてある */
export type Finding = { rule: string; message: string };

export type Violation = Finding & { from: string; to: string };

export type Judge = (from: Placement, to: Placement) => Finding | null;

/** 層の高さ。高い層は低い層を import できるが、逆はできない */
const RANK: Record<Layer, number> = { app: 3, feature: 2, 'shared-ui': 1, 'shared-lib': 0 };

/** 検査範囲のルートからの相対パス（区切りは /）で、どの層に属するかを決める */
export function placeByDirectory(path: string): Placement | null {
  const parts = path.split('/');
  const [top, second, third] = parts;
  if (top === 'app' && parts.length >= 2) return { layer: 'app', isPublic: false };
  if (top === 'shared' && second === 'ui' && parts.length >= 3) return { layer: 'shared-ui', isPublic: false };
  if (top === 'shared' && second === 'lib' && parts.length >= 3) return { layer: 'shared-lib', isPublic: false };
  if (top === 'features' && second && parts.length >= 3) {
    const isPublic = parts.length === 3 && (third === 'index.ts' || third === 'index.tsx');
    return { layer: 'feature', feature: second, isPublic };
  }
  return null;
}

/**
 * 移行前の棚卸し用。「このファイルは移行後にどのディレクトリへ行くか」の表から層を決める。
 * 移行先のパスに置いたと仮定して placeByDirectory で判定する。
 */
export function placeByPlan(plan: Readonly<Record<string, string>>): (path: string) => Placement | null {
  return (path) => {
    const destination = plan[path];
    if (destination === undefined) return null;
    const fileName = path.slice(path.lastIndexOf('/') + 1);
    return placeByDirectory(`${destination}/${fileName}`);
  };
}

export function layerLabel(p: Placement): string {
  switch (p.layer) {
    case 'app':
      return 'app';
    case 'feature':
      return `features/${p.feature ?? '?'}`;
    case 'shared-ui':
      return 'shared/ui';
    case 'shared-lib':
      return 'shared/lib';
  }
}

/** 1本の import が規則に反するかを決める。優先順位は 層の向き → feature 間 → 公開窓口 */
export function judge(from: Placement, to: Placement): (Finding & { rule: RuleId }) | null {
  if (RANK[from.layer] < RANK[to.layer]) {
    return {
      rule: 'layer',
      message: `${layerLabel(from)} から ${layerLabel(to)} へは依存できません（下の層から上の層への依存）`,
    };
  }
  if (from.layer === 'feature' && to.layer === 'feature' && from.feature !== to.feature) {
    return {
      rule: 'cross-feature',
      message: `${layerLabel(from)} から ${layerLabel(to)} を直接 import しています（feature 同士の受け渡しは app で行います）`,
    };
  }
  if (to.layer === 'feature' && from.feature !== to.feature && !to.isPublic) {
    return { rule: 'public-api', message: `${layerLabel(to)} の公開窓口（index.ts）以外を import しています` };
  }
  return null;
}

const PATTERNS = [
  // import { a } from './x' / import type { A } from './x' / export { a } from './x' / export * from './x'
  /\b(?:import|export)\s[^'"`;()=]*?\bfrom\s*['"]([^'"]+)['"]/g,
  // import './x'（副作用だけの import）
  /\bimport\s*['"]([^'"]+)['"]/g,
  // import('./x')（動的 import。lazy で使う）
  /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g,
];

/** ソースから import / export ... from の読み込み先を拾う。コメントの中は無視する */
export function extractSpecifiers(source: string): string[] {
  const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  const found = new Set<string>();
  for (const pattern of PATTERNS) {
    for (const match of code.matchAll(pattern)) {
      const specifier = match[1];
      if (specifier !== undefined) found.add(specifier);
    }
  }
  return [...found];
}

const CANDIDATE_SUFFIXES = ['', '.ts', '.tsx', '/index.ts', '/index.tsx'];

/**
 * 相対パスの読み込み先を、検査範囲のファイルに解決する。
 * パッケージ（react など）と、検査範囲の外（data/ など）を指すものは null（検査しない）。
 */
export function resolveRelative(from: string, specifier: string, files: ReadonlySet<string>): string | null {
  const relative = specifier === '.' || specifier === '..' || specifier.startsWith('./') || specifier.startsWith('../');
  if (!relative) return null;
  const segments = from.split('/').slice(0, -1);
  for (const part of specifier.split('/')) {
    if (part === '..') {
      if (segments.length === 0) return null;
      segments.pop();
    } else if (part !== '.' && part !== '') {
      segments.push(part);
    }
  }
  const base = segments.join('/');
  for (const suffix of CANDIDATE_SUFFIXES) {
    if (files.has(base + suffix)) return base + suffix;
  }
  return null;
}

const compare = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** すべてのファイルの import を判定し、違反を from → to の順に並べて返す */
export function checkDependencies(
  sources: ReadonlyMap<string, string>,
  place: (path: string) => Placement | null,
  judgeImport: Judge = judge,
): Violation[] {
  const files = new Set(sources.keys());
  const violations: Violation[] = [];
  for (const [from, source] of sources) {
    const fromPlace = place(from);
    if (fromPlace === null) {
      violations.push({ rule: 'unplaced', from, to: '', message: 'app・features・shared のどこにも属さない場所にあります' });
      continue;
    }
    for (const specifier of extractSpecifiers(source)) {
      const to = resolveRelative(from, specifier, files);
      if (to === null) continue;
      const toPlace = place(to);
      // 置き場所の違反は、読み込まれる側のファイル自身の unplaced として報告される
      if (toPlace === null) continue;
      const found = judgeImport(fromPlace, toPlace);
      if (found) violations.push({ ...found, from, to });
    }
  }
  return violations.sort((a, b) => (a.from === b.from ? compare(a.to, b.to) : compare(a.from, b.from)));
}

export function formatViolation(v: Violation): string {
  return v.to === '' ? `[${v.rule}] ${v.from} — ${v.message}` : `[${v.rule}] ${v.from} → ${v.to} — ${v.message}`;
}
