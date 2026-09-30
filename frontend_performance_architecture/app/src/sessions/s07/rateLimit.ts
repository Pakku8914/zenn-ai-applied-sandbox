/** 呼び出しが止まってから waitMs 経ったときに、最後の 1 回だけを実行する。 */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  waitMs: number,
): ((...args: A) => void) & { cancel(): void } {
  let timer: ReturnType<typeof setTimeout> | undefined;

  const debounced = (...args: A): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      fn(...args);
    }, waitMs);
  };
  const cancel = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  };
  return Object.assign(debounced, { cancel });
}

/**
 * intervalMs に 1 回まで実行する。最初の呼び出しはすぐ実行し（leading）、
 * 間隔の途中に来た呼び出しは最後の 1 回だけを間隔の終わりに実行する（trailing）。
 */
export function throttle<A extends unknown[]>(
  fn: (...args: A) => void,
  intervalMs: number,
): ((...args: A) => void) & { cancel(): void } {
  let lastRun = -Infinity;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pendingArgs: A | undefined;

  const run = (args: A): void => {
    lastRun = Date.now();
    fn(...args);
  };

  const throttled = (...args: A): void => {
    const elapsed = Date.now() - lastRun;
    if (elapsed >= intervalMs) {
      run(args);
      return;
    }
    pendingArgs = args;
    if (timer === undefined) {
      timer = setTimeout(() => {
        timer = undefined;
        if (pendingArgs !== undefined) {
          const latest = pendingArgs;
          pendingArgs = undefined;
          run(latest);
        }
      }, intervalMs - elapsed);
    }
  };
  const cancel = (): void => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    pendingArgs = undefined;
  };
  return Object.assign(throttled, { cancel });
}
