import { describe, expect, it } from 'vitest';
import { onceWithRetry } from './onceWithRetry';

describe('onceWithRetry', () => {
  it('成功した結果は使い回し、読み込みは1回だけ行う', async () => {
    let calls = 0;
    const load = onceWithRetry(async () => {
      calls += 1;
      return 'renderer';
    });
    // ホバーで先読みし、そのあとクリックした想定
    const [a, b] = await Promise.all([load(), load()]);
    expect(a).toBe('renderer');
    expect(b).toBe('renderer');
    expect(await load()).toBe('renderer');
    expect(calls).toBe(1);
  });

  it('失敗したら覚えておかず、次の呼び出しで読み込み直す', async () => {
    let calls = 0;
    const load = onceWithRetry(async () => {
      calls += 1;
      if (calls === 1) throw new Error('Failed to fetch dynamically imported module');
      return 'renderer';
    });
    await expect(load()).rejects.toThrow('Failed to fetch');
    expect(await load()).toBe('renderer');
    expect(calls).toBe(2);
  });
});
