const saved: unknown[] = [];

/** 受け取ったオブジェクトを保存しておく（中身がいつ・どう使われるかはビルド時に分からない） */
export function register(value: unknown): void {
  saved.push(value);
  Reflect.set(globalThis, '__s05Registry', saved);
}
