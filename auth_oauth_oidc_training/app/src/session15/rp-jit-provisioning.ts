// 外部 IdP から来た初回ログインで、書店側の利用者レコードを作ります（ジャストインタイムプロビジョニング）。
// 中間プロジェクトの AccountLinks（sub と注文台帳の持ち主を結び付ける対応表）を、
// 「連携先が複数ある」場合に広げたものです。
import type { ShopProfile } from "./rp-attribute-mapping.js";

/** 連携先の利用者を一意に指す鍵。sub だけでは足りません（連携先が増えると衝突します） */
export type FederatedKey = {
  /** 認証した IdP の識別子（OIDC の iss、SAML の entityID） */
  readonly issuer: string;
  /** その IdP の中で不変の識別子（OIDC の sub、SAML の NameID） */
  readonly subject: string;
};

/** Map の鍵にする文字列。issuer は URL なので、区切りに改行が現れることはありません */
export const keyOf = (key: FederatedKey): string => `${key.issuer}\n${key.subject}`;

export type ShopUser = {
  readonly userId: string;
  readonly key: FederatedKey;
  readonly profile: ShopProfile;
  /** 利用できる状態か。退職者は false にする（レコードは消さない） */
  readonly active: boolean;
  readonly createdBy: "jit" | "manual";
};

export type RejectReason = "email-conflict" | "deactivated";

export type ProvisionResult =
  | { readonly outcome: "created" | "reused" | "linked"; readonly user: ShopUser }
  | { readonly outcome: "rejected"; readonly reason: RejectReason; readonly userId: string };

export class FederatedUserStore {
  /** 連携鍵（issuer + subject）→ 書店の利用者 ID */
  private readonly idByKey = new Map<string, string>();
  private readonly users = new Map<string, ShopUser>();
  private sequence = 0;

  constructor(seed: readonly ShopUser[] = []) {
    for (const user of seed) {
      this.users.set(user.userId, user);
      this.idByKey.set(keyOf(user.key), user.userId);
    }
    this.sequence = seed.length;
  }

  /** 初回ログインでレコードを作り、2 回目以降は同じレコードを返します */
  provision(key: FederatedKey, profile: ShopProfile): ProvisionResult {
    const knownId = this.idByKey.get(keyOf(key));
    if (knownId !== undefined) {
      const known = this.users.get(knownId);
      if (known === undefined) {
        throw new Error(`対応表が壊れています: ${knownId}`);
      }
      // 退職者が再びログインしてきても、こちらで止めた状態を復活させません
      return known.active
        ? { outcome: "reused", user: known }
        : { outcome: "rejected", reason: "deactivated", userId: known.userId };
    }
    // メールアドレスが一致するだけで既存レコードにつなぐと、他人のアカウントを渡してしまいます。
    // 「同じ人かもしれない」は、本人確認の手順で決めることです（linkExisting を使う）。
    const sameEmail = this.findByEmail(profile.email);
    if (sameEmail !== undefined) {
      return { outcome: "rejected", reason: "email-conflict", userId: sameEmail.userId };
    }
    this.sequence += 1;
    const user: ShopUser = { userId: `shop-${this.sequence}`, key, profile, active: true, createdBy: "jit" };
    this.users.set(user.userId, user);
    this.idByKey.set(keyOf(key), user.userId);
    return { outcome: "created", user };
  }

  /** 本人だと確かめられたあとで、既存のレコードに連携鍵を結び付けます */
  linkExisting(key: FederatedKey, userId: string): ProvisionResult {
    const user = this.users.get(userId);
    if (user === undefined) {
      throw new Error(`存在しない利用者です: ${userId}`);
    }
    if (!user.active) {
      return { outcome: "rejected", reason: "deactivated", userId };
    }
    const linked: ShopUser = { ...user, key };
    this.users.set(userId, linked);
    this.idByKey.set(keyOf(key), userId);
    return { outcome: "linked", user: linked };
  }

  findByKey(key: FederatedKey): ShopUser | undefined {
    const id = this.idByKey.get(keyOf(key));
    return id === undefined ? undefined : this.users.get(id);
  }

  /** 連携の判断には使わず、衝突の検知にだけ使います */
  findByEmail(email: string): ShopUser | undefined {
    if (email === "") {
      return undefined;
    }
    return [...this.users.values()].find((user) => user.profile.email === email);
  }

  /** 利用を止めます。レコードは残すので、過去の注文との結び付きは切れません */
  deactivate(userId: string): boolean {
    const user = this.users.get(userId);
    if (user === undefined || !user.active) {
      return false;
    }
    this.users.set(userId, { ...user, active: false });
    return true;
  }

  /** レコードの件数（検証用） */
  get size(): number {
    return this.users.size;
  }
}
