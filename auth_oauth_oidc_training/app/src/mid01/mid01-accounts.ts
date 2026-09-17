// 中間プロジェクト mid01: トークンの sub と、書店の注文台帳の ownerId を結び付ける対応表。
//
// アクセストークンで不変の識別子は sub（セッション 8）ですが、注文台帳は利用者名（alice / bob）で
// 持ち主を記録しています。そのまま突き合わせられないので、api-service 側に対応表を 1 つ置きます。
// 初めて見た sub だけ preferred_username を頼りに結び付け、2 回目以降は sub だけで引きます。
// 実務では利用者テーブルに `subject_id` 列を持たせるのと同じ役割です（利用者名が変わっても壊れない）。

export class AccountLinks {
  private readonly ownerBySub = new Map<string, string>();

  /** sub に結び付いた書店の利用者。まだ結び付いていなければ undefined */
  ownerIdOf(sub: string): string | undefined {
    return this.ownerBySub.get(sub);
  }

  /**
   * sub を書店の利用者に結び付けます。すでに結び付いていれば、そのときの値を返します
   * （あとから利用者名が変わっても、最初に結び付けた相手を指し続けます）。
   */
  link(sub: string, username: string): string {
    const known = this.ownerBySub.get(sub);
    if (known !== undefined) {
      return known;
    }
    this.ownerBySub.set(sub, username);
    return username;
  }

  /** 結び付けた件数（検証用） */
  get size(): number {
    return this.ownerBySub.size;
  }
}
