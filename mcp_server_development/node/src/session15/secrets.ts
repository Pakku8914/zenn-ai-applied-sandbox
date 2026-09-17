/**
 * 秘密情報の型と起動時検査
 *
 * 生の string として持ち歩かないのが要点です。string には「うっかり文字列化される」
 * 経路が多すぎます（テンプレート文字列・JSON 化・console.log・例外の文面）。
 * 型で塞げるものを型で塞ぎ、残りを出口の 1 か所で消します。
 */
export const REDACTED = "[REDACTED]";

/** 文字列化のあらゆる経路を塞いだ秘密値。取り出しは reveal() だけ */
export class Secret {
  readonly #value: string;

  constructor(value: string) {
    this.#value = value;
  }

  /** 使う直前にだけ呼ぶ。呼び出し箇所を grep で数えられる状態を保つ */
  reveal(): string {
    return this.#value;
  }

  /** 長さの検査に使う。長さそのものはログに出さない */
  get length(): number {
    return this.#value.length;
  }

  toString(): string {
    return REDACTED;
  }

  toJSON(): string {
    return REDACTED;
  }

  /** console.log / util.inspect の経路も塞ぐ */
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return REDACTED;
  }
}

export type SecretSpec = {
  readonly name: string;
  readonly required: boolean;
  readonly minLength: number;
};

export const SECRET_SPECS = {
  auditPepper: { name: "AUDIT_LOG_PEPPER", required: true, minLength: 16 },
  upstreamToken: { name: "UPSTREAM_API_TOKEN", required: false, minLength: 16 },
} as const satisfies Record<string, SecretSpec>;

export type ServerSecrets = {
  readonly auditPepper: Secret;
  readonly upstreamToken: Secret | undefined;
};

export class SecretConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SecretConfigError";
  }
}

/**
 * 起動時に環境変数を検査する。足りなければ「起動させない」のが要点です。
 * 実行時に初めて気付く形にすると、原因不明の 401 やゼロ件応答として現れます。
 */
export function loadSecrets(env: NodeJS.ProcessEnv = process.env): ServerSecrets {
  return {
    auditPepper: requireSecret(env, SECRET_SPECS.auditPepper),
    upstreamToken: optionalSecret(env, SECRET_SPECS.upstreamToken),
  };
}

/** 空文字は「定義されていない」と同じに扱う（CI で空を渡す事故が多い） */
function readValue(env: NodeJS.ProcessEnv, name: string): string | undefined {
  const raw = env[name];
  return raw === undefined || raw.trim() === "" ? undefined : raw;
}

function requireSecret(env: NodeJS.ProcessEnv, spec: SecretSpec): Secret {
  const value = readValue(env, spec.name);
  if (value === undefined) {
    // 変数名は書く（直し方が分かる）。値も長さも書かない
    throw new SecretConfigError(`環境変数 ${spec.name} が設定されていません。起動を中止します。`);
  }
  if (value.length < spec.minLength) {
    throw new SecretConfigError(
      `環境変数 ${spec.name} は ${spec.minLength} 文字以上で設定してください。`,
    );
  }
  return new Secret(value);
}

function optionalSecret(env: NodeJS.ProcessEnv, spec: SecretSpec): Secret | undefined {
  const value = readValue(env, spec.name);
  if (value === undefined) {
    return undefined;
  }
  if (value.length < spec.minLength) {
    throw new SecretConfigError(
      `環境変数 ${spec.name} は ${spec.minLength} 文字以上で設定してください` +
        "（使わない場合は変数自体を定義しないでください）。",
    );
  }
  return new Secret(value);
}

/** 既知の秘密値を文字列から消す。エラーメッセージとログの出口で必ず通す */
export function redactSecrets(text: string, secrets: readonly Secret[]): string {
  let out = text;
  for (const secret of secrets) {
    const value = secret.reveal();
    // 短い値を置換対象にすると、無関係な文字列まで [REDACTED] になる
    if (value.length >= 8) {
      out = out.split(value).join(REDACTED);
    }
  }
  return out;
}
