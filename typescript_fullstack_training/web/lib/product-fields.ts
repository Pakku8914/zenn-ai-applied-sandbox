// 「どのフィールドを取るか」を1か所で決める純粋なモジュール（セッション23）。
// select / include に何を書くかがコードのあちこちに散らないようにするため。

/** 一覧用（summary）と詳細用（detail）の2種類だけを用意する */
export type ProductFieldSet = 'summary' | 'detail';

const SUMMARY_FIELDS = ['id', 'name', 'price', 'stock', 'imageUrl', 'categoryId'] as const;

const DETAIL_FIELDS = [
  'id',
  'name',
  'price',
  'stock',
  'description',
  'imageUrl',
  'categoryId',
] as const;

/** ?fields= の値を解釈する。指定なし・不正な値は一覧用に落とす */
export function parseFieldSet(raw: string | null): ProductFieldSet {
  return raw === 'detail' ? 'detail' : 'summary';
}

/** その組み合わせで取得するフィールドと、一緒に取るリレーションを返す */
export function describeFieldSet(set: ProductFieldSet): {
  fields: readonly string[];
  relations: readonly string[];
} {
  switch (set) {
    case 'summary':
      return { fields: SUMMARY_FIELDS, relations: [] };
    case 'detail':
      return { fields: DETAIL_FIELDS, relations: ['category'] };
    default: {
      const unreachable: never = set;

      throw new Error(`未知のフィールド指定です: ${String(unreachable)}`);
    }
  }
}
