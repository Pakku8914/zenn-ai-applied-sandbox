// セッション 5 の共通モジュール。
// OAuth の 4 つの役割と、その間を流れる 4 種類の情報を「データ」として書き下したものです。
// 図を眺めて終わりにせず、コードから問い合わせられる形にしてあります。

/** OAuth の 4 つの役割。本書の図と表はいつもこの順序で並べます */
export type ActorId = "resource-owner" | "client" | "authorization-server" | "resource-server";

/** 役割の間を流れる 4 種類の情報 */
export type ArtifactId =
  | "client-credentials"
  | "authorization-code"
  | "access-token"
  | "refresh-token";

export type Actor = {
  readonly id: ActorId;
  readonly label: string;
  /** 本書で固定した名前（命名規約） */
  readonly name: string;
  /** リソースオーナーのパスワードを直接扱う立場かどうか */
  readonly handlesPassword: boolean;
};

export const ACTORS: readonly Actor[] = [
  { id: "resource-owner", label: "リソースオーナー", name: "alice", handlesPassword: true },
  { id: "client", label: "クライアント", name: "web-app", handlesPassword: false },
  { id: "authorization-server", label: "認可サーバー", name: "keycloak", handlesPassword: true },
  { id: "resource-server", label: "リソースサーバー", name: "api-service", handlesPassword: false },
];

export type Artifact = {
  readonly id: ArtifactId;
  readonly label: string;
  /** 渡す側 */
  readonly from: ActorId;
  /** 受け取る側 */
  readonly to: ActorId;
  /** この情報を手にする役割（受け渡しの途中で持つ役割も含む） */
  readonly holders: readonly ActorId[];
  readonly meaning: string;
};

export const ARTIFACTS: readonly Artifact[] = [
  {
    id: "client-credentials",
    label: "クライアント資格情報",
    from: "client",
    to: "authorization-server",
    holders: ["client", "authorization-server"],
    meaning: "「このクライアントは登録済みの本物だ」の証明。機密クライアントだけが持つ",
  },
  {
    id: "authorization-code",
    label: "認可コード",
    from: "authorization-server",
    to: "client",
    holders: ["authorization-server", "client"],
    meaning: "「この利用者が許可した」ことを示す、一度しか使えない引換券",
  },
  {
    id: "access-token",
    label: "アクセストークン",
    from: "authorization-server",
    to: "client",
    holders: ["authorization-server", "client", "resource-server"],
    meaning: "「この範囲のアクセスを許す」資格情報。クライアントがリソースサーバーに提示する",
  },
  {
    id: "refresh-token",
    label: "リフレッシュトークン",
    from: "authorization-server",
    to: "client",
    holders: ["authorization-server", "client"],
    meaning: "アクセストークンを取り直す権利。リソースサーバーには渡さない",
  },
];

export function actor(id: ActorId): Actor {
  const found = ACTORS.find((a) => a.id === id);
  if (found === undefined) {
    throw new Error(`未知の役割です: ${id}`);
  }
  return found;
}

/** その役割がリソースオーナーのパスワードを直接扱うか */
export function handlesPassword(id: ActorId): boolean {
  return actor(id).handlesPassword;
}

/**
 * パスワードを扱う役割の一覧。
 * OAuth の要点は、この一覧に「クライアント」が入らないことです。
 */
export function passwordHolders(): readonly ActorId[] {
  return ACTORS.filter((a) => a.handlesPassword).map((a) => a.id);
}

/** その役割が手にする情報の一覧（ARTIFACTS の宣言順で返す） */
export function artifactsSeenBy(id: ActorId): readonly ArtifactId[] {
  return ARTIFACTS.filter((a) => a.holders.includes(id)).map((a) => a.id);
}
