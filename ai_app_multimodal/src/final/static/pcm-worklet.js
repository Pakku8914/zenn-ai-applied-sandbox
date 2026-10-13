// マイクの音を 16kHz・PCM 16bit にし、20ms（320 サンプル＝640 バイト）ずつメインのスクリプトへ渡す（セッション10と同じ）。
const OUT_RATE = 16000;
const CHUNK = 320;

class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / OUT_RATE;
    this.t = 0;
    this.prev = 0;
    this.buf = new Int16Array(CHUNK);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    while (this.t < ch.length - 1) {
      const i = Math.floor(this.t);
      const f = this.t - i;
      const a = i < 0 ? this.prev : ch[i];
      const v = Math.max(-1, Math.min(1, a * (1 - f) + ch[i + 1] * f));
      this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === CHUNK) {
        this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
        this.buf = new Int16Array(CHUNK);
        this.n = 0;
      }
      this.t += this.step;
    }
    this.t -= ch.length;
    this.prev = ch[ch.length - 1];
    return true;
  }
}

registerProcessor("pcm-sender", PcmSender);
