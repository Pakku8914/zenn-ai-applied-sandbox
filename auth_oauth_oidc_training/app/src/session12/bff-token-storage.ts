// セッション 12: 「トークンをどこに置くか」の選択肢を、守れるもの／守れないもので比べます。
// 攻撃の手口そのものは扱いません（XSS の実演は姉妹教材の担当）。
// ここでは「ブラウザの JavaScript が読める場所に置いたら、XSS が 1 つあれば読まれる」という
// 帰結だけを前提にして、選択肢を機械的に評価します。

export type StorageKind =
  | "local-storage"
  | "session-storage"
  | "memory"
  | "httponly-cookie"
  | "bff-server-side";

/** 置き場所そのものの性質。ここは「事実」だけを書き、良し悪しの判断は混ぜません */
export type StorageTraits = {
  readonly kind: StorageKind;
  readonly label: string;
  /** トークン本体がブラウザまで届くか */
  readonly reachesBrowser: boolean;
  /** ブラウザの JavaScript が中身を読めるか */
  readonly readableByScript: boolean;
  /** 画面をリロードしても残るか */
  readonly survivesReload: boolean;
  /** タブを閉じても残るか */
  readonly survivesTabClose: boolean;
  /** ブラウザが同じ相手への通信に自動で付けるか */
  readonly sentAutomatically: boolean;
};

export const STORAGE_TRAITS: readonly StorageTraits[] = [
  { kind: "local-storage", label: "localStorage", reachesBrowser: true, readableByScript: true, survivesReload: true, survivesTabClose: true, sentAutomatically: false },
  { kind: "session-storage", label: "sessionStorage", reachesBrowser: true, readableByScript: true, survivesReload: true, survivesTabClose: false, sentAutomatically: false },
  { kind: "memory", label: "JavaScript の変数（メモリ）", reachesBrowser: true, readableByScript: true, survivesReload: false, survivesTabClose: false, sentAutomatically: false },
  { kind: "httponly-cookie", label: "HttpOnly Cookie", reachesBrowser: true, readableByScript: false, survivesReload: true, survivesTabClose: true, sentAutomatically: true },
  { kind: "bff-server-side", label: "BFF のサーバー側", reachesBrowser: false, readableByScript: false, survivesReload: true, survivesTabClose: true, sentAutomatically: true },
];

export type Risk = "high" | "medium" | "low";

/** 評価の結果。すべて traits から導くので、表だけをこっそり書き換えることはできません */
export type StorageVerdict = {
  readonly kind: StorageKind;
  readonly label: string;
  /** XSS が 1 つあればトークンを持ち去られるか */
  readonly stolenByXss: boolean;
  /** ブラウザの JavaScript が Authorization ヘッダに載せて使えるか */
  readonly usableFromScript: boolean;
  /** リロードでトークンが消えるか（使い勝手の犠牲） */
  readonly lostOnReload: boolean;
  /** ブラウザが自動で送るので CSRF 対策が要るか */
  readonly needsCsrfDefense: boolean;
  readonly risk: Risk;
};

export function judge(traits: StorageTraits): StorageVerdict {
  return {
    kind: traits.kind,
    label: traits.label,
    // 「XSS から盗める」と「自分のスクリプトから使える」は、同じ性質の裏表です。
    // どちらも readableByScript から出てくるので、片方だけを選ぶことはできません。
    stolenByXss: traits.readableByScript,
    usableFromScript: traits.readableByScript,
    lostOnReload: !traits.survivesReload,
    needsCsrfDefense: traits.sentAutomatically,
    // ブラウザに届かないものは、そもそも読み出す対象がありません
    risk: !traits.reachesBrowser ? "low" : traits.readableByScript ? "high" : "medium",
  };
}

export function judgeAll(traits: readonly StorageTraits[] = STORAGE_TRAITS): readonly StorageVerdict[] {
  return traits.map(judge);
}

/** 種類を指定して 1 件だけ評価します。知らない種類は例外にします（黙って空を返さない） */
export function findVerdict(kind: StorageKind): StorageVerdict {
  const traits = STORAGE_TRAITS.find((item) => item.kind === kind);
  if (traits === undefined) {
    throw new Error(`知らない置き場所です: ${kind}`);
  }
  return judge(traits);
}
