// 検証専用の「ブラウザ役」。セッション 6 の test-helpers/headless-login.ts と同じ発想ですが、
// 役割を「渡された URL を開き、Cookie を持ち続け、次に何が起きたかを返す」だけに絞っています。
// トークン交換は RP（rp-server.ts）の仕事なので、ここでは行いません。
//
// Cookie を持ち続けるのが肝です。認可サーバー側のセッション（SSO）が残っているかどうかを、
// 「ログイン画面が出るか／出ずにリダイレクトするか」で観察できます。
// アプリの実装コードではありません（本番のクライアントは本物のブラウザに画面を表示させます）。

export type OpenResult =
  /** ログイン画面が返ってきた ＝ 認可サーバーにセッションが無い */
  | { kind: "login_form"; formAction: string }
  /** 画面を出さずにリダイレクトした ＝ 認可サーバーのセッションが生きている */
  | { kind: "redirect"; location: string }
  | { kind: "other"; status: number };

export class BrowserStub {
  private readonly jar = new Map<string, string>();

  /** Set-Cookie を取り込む。空の値で上書きされたものは「消された Cookie」として捨てる */
  private absorb(res: Response): void {
    for (const raw of res.headers.getSetCookie()) {
      const pair = raw.split(";")[0] ?? "";
      const eq = pair.indexOf("=");
      if (eq <= 0) {
        continue;
      }
      const name = pair.slice(0, eq).trim();
      const value = pair.slice(eq + 1).trim();
      if (value === "") {
        this.jar.delete(name);
      } else {
        this.jar.set(name, value);
      }
    }
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const cookie = [...this.jar].map(([name, value]) => `${name}=${value}`).join("; ");
    return cookie === "" ? extra : { ...extra, cookie };
  }

  /** 手元に残っている Cookie の名前（検証用） */
  get cookieNames(): string[] {
    return [...this.jar.keys()].sort();
  }

  /** URL を開く。リダイレクトは追わないので、認可サーバーが何を返したかがそのまま分かる */
  async open(url: string): Promise<OpenResult> {
    const res = await fetch(url, { redirect: "manual", headers: this.headers() });
    this.absorb(res);
    const location = res.headers.get("location");
    if (location !== null) {
      return { kind: "redirect", location };
    }
    const html = await res.text();
    const action = /<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"/.exec(html)?.[1];
    if (res.status === 200 && action !== undefined) {
      return { kind: "login_form", formAction: action.replaceAll("&amp;", "&") };
    }
    return { kind: "other", status: res.status };
  }

  /** ログイン画面にユーザー名とパスワードを入れて送る。戻り値はコールバックの URL */
  async submitLogin(formAction: string, username: string, password: string): Promise<string> {
    const res = await fetch(formAction, {
      method: "POST",
      redirect: "manual",
      headers: this.headers({ "content-type": "application/x-www-form-urlencoded" }),
      body: new URLSearchParams({ username, password, credentialId: "" }),
    });
    this.absorb(res);
    const location = res.headers.get("location");
    if (location === null) {
      throw new Error(`ログインがリダイレクトを返しませんでした（status ${res.status}）`);
    }
    return location;
  }
}
