import { Profiler, createContext, memo, useContext, useState } from 'react';
import { countRender } from '../renderCount';

type Theme = 'light' | 'dark';
const ThemeContext = createContext<Theme>('light');

/** props を受け取らない子。中身は毎回同じ */
function PlainChild() {
  countRender('plain');
  return <p data-part="plain">固定の文言（memo なし）</p>;
}

/** 同じ中身を memo で包んだもの */
const MemoPlainChild = memo(function MemoPlainChild() {
  countRender('memoPlain');
  return <p data-part="memo-plain">固定の文言（memo あり）</p>;
});

/** count を props で受け取る（memo あり） */
const CountLabel = memo(function CountLabel({ count }: { count: number }) {
  countRender('countLabel');
  return <p data-part="count">count：{count}</p>;
});

/** context を読む（memo あり）。memo があっても context が変われば再レンダリングされる */
const ThemeLabel = memo(function ThemeLabel() {
  countRender('themeLabel');
  const theme = useContext(ThemeContext);
  return <p data-part="theme">テーマ：{theme}</p>;
});

/** 自分の state を持つ子（memo なし） */
function SelfCounter() {
  countRender('selfCounter');
  const [n, setN] = useState(0);
  return (
    <button id="self-state" type="button" onClick={() => setN((v) => v + 1)}>
      子の state：{n}
    </button>
  );
}

/**
 * 再レンダリングの4つの条件（state・props・context・親の再レンダリング）を1画面で試す実験室。
 * Profiler の onRender も数えるが、本番ビルドでは呼ばれないので profilerOnRender は 0 のまま。
 */
export function RenderLab() {
  countRender('lab');
  const [count, setCount] = useState(0);
  const [theme, setTheme] = useState<Theme>('light');
  const [tick, setTick] = useState(0);

  return (
    <Profiler id="render-lab" onRender={() => countRender('profilerOnRender')}>
      <ThemeContext value={theme}>
        <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
          <h1>再レンダリングの実験室（S08）</h1>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button id="bump-count" type="button" onClick={() => setCount((c) => c + 1)}>
              count を増やす
            </button>
            <button id="toggle-theme" type="button" onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}>
              テーマを切り替える
            </button>
            <button id="parent-only" type="button" onClick={() => setTick((t) => t + 1)}>
              親だけの state を変える（{tick}）
            </button>
          </div>
          <PlainChild />
          <MemoPlainChild />
          <CountLabel count={count} />
          <ThemeLabel />
          <SelfCounter />
        </main>
      </ThemeContext>
    </Profiler>
  );
}
