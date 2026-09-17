// UserInfo エンドポイント。ID トークンではなく「アクセストークン」を提示して、
// いまの利用者の属性を取りに行きます（RFC 6750 の Bearer 提示）。
import { USERINFO_ENDPOINT } from "./bookstore-oidc.js";

export type UserInfoResult = {
  readonly status: number;
  readonly claims: Record<string, unknown>;
};

/** 失敗しても例外にせず status を返します。呼ぶ側が「属性が取れなかった」を扱えるようにするためです */
export async function fetchUserInfo(accessToken: string): Promise<UserInfoResult> {
  const res = await fetch(USERINFO_ENDPOINT, {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    return { status: res.status, claims: {} };
  }
  return { status: res.status, claims: (await res.json()) as Record<string, unknown> };
}
