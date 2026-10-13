// マイクの音を 16kHz・PCM 16bit にし、20ms（320 サンプル＝640 バイト）ずつメインのスクリプトへ渡す（セッション10からそのままコピー）。
// AudioWorklet は音声専用のスレッドで動き、process() は 128 サンプルずつ呼ばれる。
// sampleRate は AudioContext のレート（端末によって違う。多くは 48000Hz か 44100Hz）。
const OUT_RATE = 16000;
const CHUNK = 320;

class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / OUT_RATE; // 出力を1サンプル進めるのに、入力を何サンプル進めるか（48000Hz なら 3）
    this.t = 0;                        // 次に取り出す位置（このブロックの先頭を 0 とする。-1 は前のブロックの最後）
    this.prev = 0;                     // 前のブロックの最後のサンプル（補間に使う）
    this.buf = new Int16Array(CHUNK);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];      // 1つ目の入力の1チャンネル目（モノラルとして扱う）
    if (!ch || ch.length === 0) return true;   // マイクがまだつながっていない
    while (this.t < ch.length - 1) {
      const i = Math.floor(this.t);
      const f = this.t - i;
      const a = i < 0 ? this.prev : ch[i];
      const v = Math.max(-1, Math.min(1, a * (1 - f) + ch[i + 1] * f)); // 前後のサンプルから線形補間
      this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;             // -1.0〜1.0 → -32768〜32767
      if (this.n === CHUNK) {
        this.port.postMessage(this.buf.buffer, [this.buf.buffer]);      // コピーせずに渡す
        this.buf = new Int16Array(CHUNK);
        this.n = 0;
      }
      this.t += this.step;
    }
    this.t -= ch.length;
    this.prev = ch[ch.length - 1];
    return true; // true を返すと、次のブロックでも呼ばれる
  }
}

registerProcessor("pcm-sender", PcmSender);
