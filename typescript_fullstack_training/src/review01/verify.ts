/**
 * 復習01「セッション1〜10の横断復習」の練習問題の解答を検証する。
 * 章に載せた「期待される出力」と1文字でも違えばエラー終了する。
 *
 */

/** 比較できる値（=== の暗黙変換を避けるため、比較は常に !== で行う） */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}`);
    console.error(`  期待値: ${String(expected)}`);
    console.error(`  実際　: ${String(actual)}`);
    process.exit(1);
  }
};

/** 商品（本書共通のマスタと同じ形） */
type Product = { id: number; name: string; price: number; stock: number; categoryId: number };

/** 商品マスタ（requirements.md の固定表と一致させる） */
const PRODUCTS: Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
  { id: 4, name: 'リネンのふきん', price: 990, stock: 0, categoryId: 3 },
  { id: 5, name: 'コットンのトートバッグ', price: 2800, stock: 5, categoryId: 3 },
];

/** カテゴリマスタ */
const CATEGORIES = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

// 本書共通の定数
const TAX_RATE = 0.1;
const SHIPPING_FEE = 500;
const FREE_SHIPPING_THRESHOLD = 3000;

/** 数値を右そろえの文字列にする（S05 の padAmount と同じ形） */
const padAmount = (amount: number, width: number): string => String(amount).padStart(width, ' ');

/** 整数の金額を3桁区切りの文字列にする */
const formatYen = (amount: number): string => {
  let rest = String(amount);
  let grouped = '';
  while (rest.length > 3) {
    grouped = `,${rest.slice(rest.length - 3)}${grouped}`;
    rest = rest.slice(0, rest.length - 3);
  }
  return `${rest}${grouped}円`;
};

// 3桁区切りの単体確認
check('formatYen(0)', formatYen(0), '0円');
check('formatYen(480)', formatYen(480), '480円');
check('formatYen(1000)', formatYen(1000), '1,000円');
check('formatYen(54170)', formatYen(54170), '54,170円');
check('formatYen(1234567)', formatYen(1234567), '1,234,567円');

// ---------------------------------------------------------------------------
// 問題1：商品1件の情報を組み立てる（S01・S02・S03・S07）
// ---------------------------------------------------------------------------
const q1ProductName: string = 'ラベンダーの石けん';
const q1Price: number = 480;
const q1Stock: number = 24;
const q1ImageUrl: string = '/images/products/lavender-soap.png';

const q1PriceWithTax = Math.floor(q1Price * (1 + TAX_RATE));
const Q1_BOX_SIZE = 5;
const q1BoxCount = Math.floor(q1Stock / Q1_BOX_SIZE);
const q1Remainder = q1Stock % Q1_BOX_SIZE;
const q1StockLabel = q1Stock > 0 ? '在庫あり' : '在庫切れ';
const q1PathParts = q1ImageUrl.split('/');
const q1FileName = q1PathParts.at(-1) ?? '';
const q1Slug = q1FileName.replaceAll('.png', '');
const q1FirstWord = q1Slug.split('-').at(0) ?? '';

check('問題1：商品名の文字数', q1ProductName.length, 9);
check('問題1：税込価格', q1PriceWithTax, 528);
check('問題1：割り算は小数になる', q1Stock / Q1_BOX_SIZE, 4.8);
check('問題1：箱の数', q1BoxCount, 4);
check('問題1：余り', q1Remainder, 4);
check('問題1：slug', q1Slug, 'lavender-soap');

const q1Report = [
  `${q1ProductName}（${q1ProductName.length}文字）: 税抜 ${q1Price}円 / 税込 ${q1PriceWithTax}円`,
  `在庫 ${q1Stock}個 → ${Q1_BOX_SIZE}個入りの箱が ${q1BoxCount}箱、余り ${q1Remainder}個` +
    `（${q1Stock} / ${Q1_BOX_SIZE} = ${q1Stock / Q1_BOX_SIZE}）`,
  `在庫状態: ${q1StockLabel}`,
  `slug: ${q1Slug} / soap を含む: ${q1Slug.includes('soap')} / 先頭の語: ${q1FirstWord}`,
].join('\n');

check(
  '問題1の出力',
  q1Report,
  [
    'ラベンダーの石けん（9文字）: 税抜 480円 / 税込 528円',
    '在庫 24個 → 5個入りの箱が 4箱、余り 4個（24 / 5 = 4.8）',
    '在庫状態: 在庫あり',
    'slug: lavender-soap / soap を含む: true / 先頭の語: lavender',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題2：在庫一覧を桁をそろえて表示する（S04・S07・S08・S02・S03）
// ---------------------------------------------------------------------------
const stockNote = (stock: number): string => {
  if (stock === 0) {
    return ' ← 在庫切れ';
  }
  if (stock <= 5) {
    return ' ← 残りわずか';
  }
  return '';
};

check('問題2：在庫0の注記', stockNote(0), ' ← 在庫切れ');
check('問題2：境界値5の注記', stockNote(5), ' ← 残りわずか');
check('問題2：境界値6の注記', stockNote(6), '');

const q2Lines: string[] = [];
let q2No = 0;
let q2SellableCount = 0;
let q2SoldOutCount = 0;

for (const product of PRODUCTS) {
  q2No += 1;
  if (product.stock === 0) {
    q2SoldOutCount += 1;
  } else {
    q2SellableCount += 1;
  }
  q2Lines.push(
    `No.${q2No} ${product.name} / 単価 ${padAmount(product.price, 5)}円 / ` +
      `在庫 ${padAmount(product.stock, 2)}個${stockNote(product.stock)}`
  );
}
q2Lines.push(
  `合計 ${PRODUCTS.length}件 / 販売可能 ${q2SellableCount}件 / 在庫切れ ${q2SoldOutCount}件`
);

check(
  '問題2の出力',
  q2Lines.join('\n'),
  [
    'No.1 ラベンダーの石けん / 単価   480円 / 在庫 24個',
    'No.2 ハンドクリーム / 単価  1800円 / 在庫 12個',
    'No.3 マグカップ / 単価  2350円 / 在庫  3個 ← 残りわずか',
    'No.4 リネンのふきん / 単価   990円 / 在庫  0個 ← 在庫切れ',
    'No.5 コットンのトートバッグ / 単価  2800円 / 在庫  5個 ← 残りわずか',
    '合計 5件 / 販売可能 4件 / 在庫切れ 1件',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題3：在庫金額を集計して3桁区切りで表示する（S10・S02・S04・S09）
// ---------------------------------------------------------------------------
const q3Sellable = PRODUCTS.filter((product) => product.stock > 0);
const q3StockValues = q3Sellable.map((product) => ({
  name: product.name,
  stockValue: product.price * product.stock,
}));
const q3TotalSellable = q3StockValues.reduce((sum, row) => sum + row.stockValue, 0);
const q3TotalAll = PRODUCTS.reduce((sum, product) => sum + product.price * product.stock, 0);

check('問題3：販売可能な件数', q3Sellable.length, 4);
check('問題3：合計（販売可能のみ）', q3TotalSellable, 54170);
check('問題3：合計（全件）', q3TotalAll, 54170);
check('問題3：元の配列は壊れていない', PRODUCTS.length, 5);
check('問題3：filter は新しい配列を返す', PRODUCTS === q3Sellable, false);

const q3Lines: string[] = [`販売可能な商品: ${q3Sellable.length}件`];
for (const row of q3StockValues) {
  q3Lines.push(`  ${row.name}: ${formatYen(row.stockValue)}`);
}
q3Lines.push(`在庫金額の合計（販売可能のみ）: ${formatYen(q3TotalSellable)}`);
q3Lines.push(`在庫金額の合計（在庫切れを含む全件）: ${formatYen(q3TotalAll)}`);
q3Lines.push(
  `元の配列: ${PRODUCTS.length}件 / filter の結果は同じ配列か: ${PRODUCTS === q3Sellable}`
);

check(
  '問題3の出力',
  q3Lines.join('\n'),
  [
    '販売可能な商品: 4件',
    '  ラベンダーの石けん: 11,520円',
    '  ハンドクリーム: 21,600円',
    '  マグカップ: 7,050円',
    '  コットンのトートバッグ: 14,000円',
    '在庫金額の合計（販売可能のみ）: 54,170円',
    '在庫金額の合計（在庫切れを含む全件）: 54,170円',
    '元の配列: 5件 / filter の結果は同じ配列か: false',
  ].join('\n')
);

// 別解（toLocaleString）が同じ結果になることも確認する
check('問題3 別解：toLocaleString', `${(54170).toLocaleString('ja-JP')}円`, '54,170円');

// ---------------------------------------------------------------------------
// 問題4：カテゴリを紐づけて集計する（S08・S10・S07・S03）
// ---------------------------------------------------------------------------
const categoryNameById = new Map<number, string>();
for (const category of CATEGORIES) {
  categoryNameById.set(category.id, category.name);
}
const categoryNameOf = (categoryId: number): string =>
  categoryNameById.get(categoryId) ?? '未分類';

check('問題4：カテゴリ名を引く', categoryNameOf(2), 'キッチン雑貨');
check('問題4：存在しないIDは未分類', categoryNameOf(99), '未分類');
check('問題4：Map の件数', categoryNameById.size, 3);

const q4UsedCategoryIds = [...new Set(PRODUCTS.map((product) => product.categoryId))];
check('問題4：重複排除したカテゴリID', q4UsedCategoryIds.join(', '), '1, 2, 3');
check('問題4：カテゴリの種類数', q4UsedCategoryIds.length, 3);

const q4Summaries = CATEGORIES.map((category) => {
  const items = PRODUCTS.filter((product) => product.categoryId === category.id);
  const stockValue = items.reduce((sum, product) => sum + product.price * product.stock, 0);
  return { name: category.name, slug: category.slug, count: items.length, stockValue };
});
const q4Ranked = q4Summaries.toSorted((a, b) => b.stockValue - a.stockValue);
const q4Top = q4Ranked.at(0);
const q4TopText = q4Top === undefined ? 'なし' : `${q4Top.name}（${formatYen(q4Top.stockValue)}）`;

check('問題4：カテゴリ別の合計が全体と一致する', q4Summaries.reduce((s, r) => s + r.stockValue, 0), 54170);
check('問題4：toSorted は元の配列を壊さない', q4Summaries.at(0)?.name ?? '', 'バス・ボディケア');

const q4Lines: string[] = [
  `使われているカテゴリID: ${q4UsedCategoryIds.join(', ')}（${q4UsedCategoryIds.length}種類）`,
];
for (const summary of q4Summaries) {
  q4Lines.push(
    `${summary.name}（${summary.slug}）: ${summary.count}件 / 在庫金額 ${formatYen(summary.stockValue)}`
  );
}
q4Lines.push(`categoryId=99 のカテゴリ名: ${categoryNameOf(99)}`);
q4Lines.push(`在庫金額が最大のカテゴリ: ${q4TopText}`);

check(
  '問題4の出力',
  q4Lines.join('\n'),
  [
    '使われているカテゴリID: 1, 2, 3（3種類）',
    'バス・ボディケア（bath-body）: 2件 / 在庫金額 33,120円',
    'キッチン雑貨（kitchen）: 1件 / 在庫金額 7,050円',
    'ファブリック（fabric）: 2件 / 在庫金額 14,000円',
    'categoryId=99 のカテゴリ名: 未分類',
    '在庫金額が最大のカテゴリ: バス・ボディケア（33,120円）',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題5：支払総額を関数に分けて計算する（S05・S06・S03・S02・S10）
// ---------------------------------------------------------------------------
const calcLineTotal = (price: number, quantity: number): number => price * quantity;

const calcSubtotal = (lines: { price: number; quantity: number }[]): number =>
  lines.reduce((sum, line) => sum + calcLineTotal(line.price, line.quantity), 0);

const calcDiscountAmount = (subtotal: number, percent: number): number =>
  Math.floor((subtotal * percent) / 100);

const calcTax = (discountedTotal: number, rate = TAX_RATE): number =>
  Math.floor(discountedTotal * rate);

const calcShippingFee = (totalWithTax: number): number =>
  totalWithTax >= FREE_SHIPPING_THRESHOLD ? 0 : SHIPPING_FEE;

const calcPayableAmount = (subtotal: number, rule: (subtotal: number) => number): number => {
  const discountedTotal = subtotal - rule(subtotal);
  const totalWithTax = discountedTotal + calcTax(discountedTotal);
  return totalWithTax + calcShippingFee(totalWithTax);
};

const makePercentDiscount = (percent: number): ((subtotal: number) => number) => {
  return (subtotal: number): number => calcDiscountAmount(subtotal, percent);
};

const resolveMemberRank = (totalSpent: number): string => {
  if (totalSpent >= 50000) {
    return 'gold';
  }
  if (totalSpent >= 20000) {
    return 'silver';
  }
  if (totalSpent >= 5000) {
    return 'bronze';
  }
  return 'none';
};

const discountPercentByRank = (rank: string): number => {
  switch (rank) {
    case 'gold':
      return 10;
    case 'silver':
      return 5;
    case 'bronze':
      return 3;
    default:
      return 0;
  }
};

const resolveDiscountRule = (rank: string): ((subtotal: number) => number) =>
  makePercentDiscount(discountPercentByRank(rank));

const buildOrderReport = (
  label: string,
  lines: { price: number; quantity: number }[],
  totalSpent: number
): string => {
  const subtotal = calcSubtotal(lines);
  const rank = resolveMemberRank(totalSpent);
  const percent = discountPercentByRank(rank);
  const rule = resolveDiscountRule(rank);
  const discountAmount = rule(subtotal);
  const discountedTotal = subtotal - discountAmount;
  const tax = calcTax(discountedTotal);
  const totalWithTax = discountedTotal + tax;
  const shippingFee = calcShippingFee(totalWithTax);
  const payableAmount = calcPayableAmount(subtotal, rule);
  return (
    `${label}：小計 ${subtotal}円 → 割引 ${discountAmount}円（${rank} ${percent}%）` +
    `→ 税 ${tax}円 → 税込 ${totalWithTax}円 → 送料 ${shippingFee}円 → 支払 ${payableAmount}円`
  );
};

// 会員ランクの境界値
check('問題5：ランク（4800円）', resolveMemberRank(4800), 'none');
check('問題5：ランク（5000円）', resolveMemberRank(5000), 'bronze');
check('問題5：ランク（20000円）', resolveMemberRank(20000), 'silver');
check('問題5：ランク（50000円）', resolveMemberRank(50000), 'gold');
check('問題5：割引率（none）', discountPercentByRank('none'), 0);
check('問題5：割引率（gold）', discountPercentByRank('gold'), 10);
check('問題5：クロージャが割引率を覚えている', makePercentDiscount(10)(2830), 283);

const q5OrderA = [{ name: 'ラベンダーの石けん', price: 480, quantity: 2 }];
const q5OrderB = [
  { name: 'ラベンダーの石けん', price: 480, quantity: 1 },
  { name: 'マグカップ', price: 2350, quantity: 1 },
];
const q5OrderC = [
  { name: 'マグカップ', price: 2350, quantity: 1 },
  { name: 'コットンのトートバッグ', price: 2800, quantity: 1 },
];

// 支払総額の計算手順を1ステップずつ確認する（注文B・gold 10%）
check('問題5 手順1 小計', calcSubtotal(q5OrderB), 2830);
check('問題5 手順2 割引額', calcDiscountAmount(2830, 10), 283);
check('問題5 手順3 割引後小計', 2830 - 283, 2547);
check('問題5 手順4 消費税', calcTax(2547), 254);
check('問題5 手順5 税込商品合計', 2547 + 254, 2801);
check('問題5 手順6 送料（税込2801円）', calcShippingFee(2801), 500);
check('問題5 手順7 支払総額', 2801 + 500, 3301);
// 割引しない場合は税込3113円で送料無料になる（税抜2830円では判定しない）
check('問題5 割引なしの消費税', calcTax(2830), 283);
check('問題5 割引なしの税込商品合計', 2830 + 283, 3113);
check('問題5 割引なしの送料', calcShippingFee(3113), 0);

const q5NoDiscountRule = makePercentDiscount(0);
const q5SubtotalB = calcSubtotal(q5OrderB);
const q5PlainDiscounted = q5SubtotalB - q5NoDiscountRule(q5SubtotalB);
const q5PlainTotalWithTax = q5PlainDiscounted + calcTax(q5PlainDiscounted);
const q5PlainPayable = calcPayableAmount(q5SubtotalB, q5NoDiscountRule);
const q5GoldPayable = calcPayableAmount(
  q5SubtotalB,
  resolveDiscountRule(resolveMemberRank(62000))
);

const q5Lines = [
  buildOrderReport('注文A', q5OrderA, 4800),
  buildOrderReport('注文B', q5OrderB, 62000),
  buildOrderReport('注文C', q5OrderC, 21000),
  `注文Bの検算：割引なしなら 税込${q5PlainTotalWithTax}円で送料無料 → 支払 ${q5PlainPayable}円` +
    `（割引ありのほうが ${q5GoldPayable - q5PlainPayable}円 高い）`,
];

check(
  '問題5の出力',
  q5Lines.join('\n'),
  [
    '注文A：小計 960円 → 割引 0円（none 0%）→ 税 96円 → 税込 1056円 → 送料 500円 → 支払 1556円',
    '注文B：小計 2830円 → 割引 283円（gold 10%）→ 税 254円 → 税込 2801円 → 送料 500円 → 支払 3301円',
    '注文C：小計 5150円 → 割引 257円（silver 5%）→ 税 489円 → 税込 5382円 → 送料 0円 → 支払 5382円',
    '注文Bの検算：割引なしなら 税込3113円で送料無料 → 支払 3113円（割引ありのほうが 188円 高い）',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題6：商品を名前で検索する（S10・S02・S07・S03）
// ---------------------------------------------------------------------------
type SearchTarget = { id: number; name: string; price: number; description: string };

const SEARCH_TARGETS: SearchTarget[] = [
  {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
  },
  {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
  },
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
  },
  {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
  },
  {
    id: 5,
    name: 'コットンのトートバッグ',
    price: 2800,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
  },
];

const searchProducts = (products: SearchTarget[], keyword: string): SearchTarget[] => {
  const trimmed = keyword.trim();
  if (trimmed === '') {
    return products.toSorted((a, b) => a.price - b.price);
  }
  const needle = trimmed.toLowerCase();
  return products
    .filter((product) => `${product.name} ${product.description}`.toLowerCase().includes(needle))
    .toSorted((a, b) => a.price - b.price);
};

const formatResult = (keyword: string, results: { name: string; price: number }[]): string => {
  if (results.length === 0) {
    return `検索「${keyword}」: 0件 → 該当なし`;
  }
  const names = results.map((product) => `${product.name}（${product.price}円）`).join(', ');
  return `検索「${keyword}」: ${results.length}件 → ${names}`;
};

check('問題6：キーワード「マグ」の件数', searchProducts(SEARCH_TARGETS, 'マグ').length, 1);
check('問題6：大文字小文字を無視する', searchProducts(SEARCH_TARGETS, 'a4').length, 1);
check('問題6：大文字でも同じ結果', searchProducts(SEARCH_TARGETS, 'A4').length, 1);
check('問題6：空白だけなら全件', searchProducts(SEARCH_TARGETS, '  ').length, 5);
check('問題6：前後の空白は無視する', searchProducts(SEARCH_TARGETS, '  マグ  ').length, 1);
check('問題6：該当なし', searchProducts(SEARCH_TARGETS, 'タオル').length, 0);
check('問題6：元の配列は壊れていない', SEARCH_TARGETS.at(0)?.name ?? '', 'ラベンダーの石けん');

const q6Lines = [
  formatResult('マグ', searchProducts(SEARCH_TARGETS, 'マグ')),
  formatResult('a4', searchProducts(SEARCH_TARGETS, 'a4')),
  formatResult('  ', searchProducts(SEARCH_TARGETS, '  ')),
  formatResult('タオル', searchProducts(SEARCH_TARGETS, 'タオル')),
  `元の配列: ${SEARCH_TARGETS.length}件 / 先頭は ${SEARCH_TARGETS.at(0)?.name ?? '（商品がありません）'}（並べ替えても壊れていない）`,
];

check(
  '問題6の出力',
  q6Lines.join('\n'),
  [
    '検索「マグ」: 1件 → マグカップ（2350円）',
    '検索「a4」: 1件 → コットンのトートバッグ（2800円）',
    '検索「  」: 5件 → ラベンダーの石けん（480円）, リネンのふきん（990円）, ハンドクリーム（1800円）, マグカップ（2350円）, コットンのトートバッグ（2800円）',
    '検索「タオル」: 0件 → 該当なし',
    '元の配列: 5件 / 先頭は ラベンダーの石けん（並べ替えても壊れていない）',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題7・問題9 共通の部品：採番と追加（S09・S10・S03・S08）
// ---------------------------------------------------------------------------
const INITIAL_PRODUCTS: Product[] = [
  { id: 1, name: 'ラベンダーの石けん', price: 480, stock: 24, categoryId: 1 },
  { id: 2, name: 'ハンドクリーム', price: 1800, stock: 12, categoryId: 1 },
  { id: 3, name: 'マグカップ', price: 2350, stock: 3, categoryId: 2 },
];

const nextProductId = (products: { id: number }[]): number =>
  products.reduce((maxId, product) => Math.max(maxId, product.id), 0) + 1;

const addProduct = (
  products: Product[],
  input: { name: string; price: number; stock: number; categoryId: number }
): { ok: boolean; message: string; products: Product[] } => {
  const name = input.name.trim();
  if (name === '') {
    return { ok: false, message: '商品名を入力してください', products };
  }
  if (!Number.isInteger(input.price) || input.price < 0) {
    return { ok: false, message: '価格は0以上の整数で入力してください', products };
  }
  if (!Number.isInteger(input.stock) || input.stock < 0) {
    return { ok: false, message: '在庫数は0以上の整数で入力してください', products };
  }
  if (products.some((product) => product.name === name)) {
    return { ok: false, message: '同じ名前の商品が既に登録されています', products };
  }
  const added = {
    id: nextProductId(products),
    name,
    price: input.price,
    stock: input.stock,
    categoryId: input.categoryId,
  };
  return {
    ok: true,
    message: `${added.name} を登録しました（id=${added.id}）`,
    products: [...products, added],
  };
};

check('問題7：空配列の採番', nextProductId([]), 1);
check('問題7：3件の採番', nextProductId(INITIAL_PRODUCTS), 4);

const q7Report = (
  no: string,
  label: string,
  ok: boolean,
  message: string,
  count: number
): string => `${no} ${label} → ${ok ? 'OK' : 'NG'}: ${message} / ${count}件`;

const q7Step1 = addProduct(INITIAL_PRODUCTS, {
  name: 'リネンのふきん',
  price: 990,
  stock: 0,
  categoryId: 3,
});
const q7Step2 = addProduct(q7Step1.products, {
  name: 'コットンのトートバッグ',
  price: 2800,
  stock: 5,
  categoryId: 3,
});
const q7Step3 = addProduct(q7Step2.products, {
  name: '   ',
  price: 990,
  stock: 0,
  categoryId: 3,
});
const q7Step4 = addProduct(q7Step3.products, {
  name: 'マグカップ',
  price: 2350,
  stock: 3,
  categoryId: 2,
});
const q7Step5 = addProduct(q7Step4.products, {
  name: 'リネンのふきん',
  price: -990,
  stock: 0,
  categoryId: 3,
});
const q7Step6 = addProduct(q7Step5.products, {
  name: 'マグカップ',
  price: 2350.5,
  stock: 3,
  categoryId: 2,
});

check('問題7：①は成功', q7Step1.ok, true);
check('問題7：②で5件になる', q7Step2.products.length, 5);
check('問題7：③は名前で失敗', q7Step3.ok, false);
check('問題7：④は重複で失敗', q7Step4.message, '同じ名前の商品が既に登録されています');
check('問題7：⑤は価格で失敗', q7Step5.message, '価格は0以上の整数で入力してください');
check('問題7：⑥はガードの順序で価格が先に落ちる', q7Step6.message, '価格は0以上の整数で入力してください');
check('問題7：元の配列は3件のまま', INITIAL_PRODUCTS.length, 3);
check('問題7：追加後の配列は別物', q7Step2.products === INITIAL_PRODUCTS, false);
check('問題7：失敗時は同じ配列を返す', q7Step3.products === q7Step2.products, true);
check('問題7：次に採番されるID', nextProductId(q7Step6.products), 6);

const q7Lines = [
  `初期: ${INITIAL_PRODUCTS.length}件（${INITIAL_PRODUCTS.map((p) => p.name).join(', ')}）`,
  q7Report('①', 'リネンのふきん', q7Step1.ok, q7Step1.message, q7Step1.products.length),
  q7Report('②', 'コットンのトートバッグ', q7Step2.ok, q7Step2.message, q7Step2.products.length),
  q7Report('③', '「   」', q7Step3.ok, q7Step3.message, q7Step3.products.length),
  q7Report('④', 'マグカップ（2350円）', q7Step4.ok, q7Step4.message, q7Step4.products.length),
  q7Report('⑤', 'リネンのふきん（-990円）', q7Step5.ok, q7Step5.message, q7Step5.products.length),
  q7Report('⑥', 'マグカップ（2350.5円）', q7Step6.ok, q7Step6.message, q7Step6.products.length),
  `最初のリスト: ${INITIAL_PRODUCTS.length}件（addProduct は元の配列を変えない）`,
  `次に採番されるID: ${nextProductId(q7Step6.products)}`,
];

check(
  '問題7の出力',
  q7Lines.join('\n'),
  [
    '初期: 3件（ラベンダーの石けん, ハンドクリーム, マグカップ）',
    '① リネンのふきん → OK: リネンのふきん を登録しました（id=4） / 4件',
    '② コットンのトートバッグ → OK: コットンのトートバッグ を登録しました（id=5） / 5件',
    '③ 「   」 → NG: 商品名を入力してください / 5件',
    '④ マグカップ（2350円） → NG: 同じ名前の商品が既に登録されています / 5件',
    '⑤ リネンのふきん（-990円） → NG: 価格は0以上の整数で入力してください / 5件',
    '⑥ マグカップ（2350.5円） → NG: 価格は0以上の整数で入力してください / 5件',
    '最初のリスト: 3件（addProduct は元の配列を変えない）',
    '次に採番されるID: 6',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題8：5つのバグを見つけて直す（S02・S03・S07・S09・S10）
// ---------------------------------------------------------------------------

// ① 空白だけのキーワードを truthy と判定してしまう
const q8SearchByNameBad = (
  products: { name: string }[],
  keyword: string
): { name: string }[] => {
  if (keyword) {
    return products.filter((product) => product.name.includes(keyword));
  }
  return products;
};
const q8SearchByName = (products: { name: string }[], keyword: string): { name: string }[] => {
  const trimmed = keyword.trim();
  if (trimmed === '') {
    return products;
  }
  return products.filter((product) => product.name.includes(trimmed));
};
check('問題8①：修正前は0件', q8SearchByNameBad(PRODUCTS, '   ').length, 0);
check('問題8①：修正後は全件', q8SearchByName(PRODUCTS, '   ').length, 5);

// ② 0 は falsy なので既定値に化ける
const q8ResolveDiscountPercentBad = (inputPercent?: number): number => inputPercent || 3;
const q8ResolveDiscountPercent = (inputPercent?: number): number => inputPercent ?? 3;
check('問題8②：修正前は3%', q8ResolveDiscountPercentBad(0), 3);
check('問題8②：修正後は0%', q8ResolveDiscountPercent(0), 0);
check('問題8②：未指定なら既定値', q8ResolveDiscountPercent(undefined), 3);

// ③ sort は破壊的・toSorted は非破壊
const q8SortByPriceDescBad = (
  products: { name: string; price: number }[]
): { name: string; price: number }[] => products.sort((a, b) => b.price - a.price);
const q8SortByPriceDesc = (
  products: { name: string; price: number }[]
): { name: string; price: number }[] => products.toSorted((a, b) => b.price - a.price);

const q8CopiedForBad = [...PRODUCTS];
q8SortByPriceDescBad(q8CopiedForBad);
const q8BadFirst = q8CopiedForBad.at(0);
const q8CopiedForGood = [...PRODUCTS];
q8SortByPriceDesc(q8CopiedForGood);
const q8GoodFirst = q8CopiedForGood.at(0);
check('問題8③：修正前は渡した配列が壊れる', q8BadFirst?.name ?? '', 'コットンのトートバッグ');
check('問題8③：修正後は無傷', q8GoodFirst?.name ?? '', 'ラベンダーの石けん');
check('問題8③：共通データは無傷', PRODUCTS.at(0)?.name ?? '', 'ラベンダーの石けん');

// ④ インデックスアクセスは undefined を含む（修正前は TS18048 で型チェックが失敗する）
const q8FirstProduct = PRODUCTS.at(0);
const q8FirstName = q8FirstProduct === undefined ? '（商品がありません）' : q8FirstProduct.name;
check('問題8④：ガード節で undefined を弾く', q8FirstName, 'ラベンダーの石けん');

// ⑤ 浮動小数点誤差
const q8WithTaxBad = (price: number): number => price * (1 + TAX_RATE);
const q8WithTax = (price: number): number => Math.floor(price * (1 + TAX_RATE));
const q8HandCream = PRODUCTS.at(1);
const q8HandCreamPrice = q8HandCream === undefined ? 0 : q8HandCream.price;
check('問題8⑤：修正前は小数が残る', String(q8WithTaxBad(q8HandCreamPrice)), '1980.0000000000002');
check('問題8⑤：修正後は整数の円', q8WithTax(q8HandCreamPrice), 1980);

const q8Lines = [
  `① 空白だけのキーワードの検索件数: 修正前 ${q8SearchByNameBad(PRODUCTS, '   ').length}件 / ` +
    `修正後 ${q8SearchByName(PRODUCTS, '   ').length}件`,
  `② 割引率に0を渡したときの適用率: 修正前 ${q8ResolveDiscountPercentBad(0)}% / ` +
    `修正後 ${q8ResolveDiscountPercent(0)}%`,
  `③ 価格の降順に並べたあとの元の配列の先頭: ` +
    `修正前 ${q8BadFirst === undefined ? 'なし' : q8BadFirst.name} / ` +
    `修正後 ${q8GoodFirst === undefined ? 'なし' : q8GoodFirst.name}`,
  `④ 先頭の商品名: 修正後 ${q8FirstName}（修正前は tsc --noEmit が TS18048 で失敗）`,
  `⑤ ハンドクリームの税込価格: 修正前 ${q8WithTaxBad(q8HandCreamPrice)}円 / ` +
    `修正後 ${q8WithTax(q8HandCreamPrice)}円`,
];

check(
  '問題8の出力',
  q8Lines.join('\n'),
  [
    '① 空白だけのキーワードの検索件数: 修正前 0件 / 修正後 5件',
    '② 割引率に0を渡したときの適用率: 修正前 3% / 修正後 0%',
    '③ 価格の降順に並べたあとの元の配列の先頭: 修正前 コットンのトートバッグ / 修正後 ラベンダーの石けん',
    '④ 先頭の商品名: 修正後 ラベンダーの石けん（修正前は tsc --noEmit が TS18048 で失敗）',
    '⑤ ハンドクリームの税込価格: 修正前 1980.0000000000002円 / 修正後 1980円',
  ].join('\n')
);

// ---------------------------------------------------------------------------
// 問題9：在庫管理ツールの部品を組み立てる（S02〜S10 の総合）
// ---------------------------------------------------------------------------
const formatProductLine = (
  product: { id: number; name: string; price: number; stock: number },
  categoryName: string
): string => {
  const note = product.stock === 0 ? '（在庫切れ）' : '';
  return (
    `[${product.id}] ${product.name} / ${categoryName} / ${padAmount(product.price, 5)}円 / ` +
    `在庫 ${padAmount(product.stock, 2)}個${note}`
  );
};

const searchByName = (
  products: { name: string; price: number }[],
  keyword: string
): { name: string; price: number }[] => {
  const trimmed = keyword.trim();
  if (trimmed === '') {
    return products.toSorted((a, b) => a.price - b.price);
  }
  const needle = trimmed.toLowerCase();
  return products
    .filter((product) => product.name.toLowerCase().includes(needle))
    .toSorted((a, b) => a.price - b.price);
};

const calcTotalStockValue = (products: { price: number; stock: number }[]): number =>
  products.reduce((sum, product) => sum + product.price * product.stock, 0);

const q9AfterFirst = addProduct(INITIAL_PRODUCTS, {
  name: 'リネンのふきん',
  price: 990,
  stock: 0,
  categoryId: 3,
});
const q9AfterSecond = addProduct(q9AfterFirst.products, {
  name: 'コットンのトートバッグ',
  price: 2800,
  stock: 5,
  categoryId: 3,
});
const q9Products = q9AfterSecond.products;
const q9Found = searchByName(q9Products, 'の');
const q9Sellable = q9Products.filter((product) => product.stock > 0);
const q9SoldOut = q9Products.filter((product) => product.stock === 0);

check('問題9：追加後は5件', q9Products.length, 5);
check('問題9：検索「の」は3件', q9Found.length, 3);
check('問題9：在庫金額の合計', calcTotalStockValue(q9Products), 54170);
check('問題9：販売可能な件数', q9Sellable.length, 4);
check('問題9：在庫切れの件数', q9SoldOut.length, 1);
check('問題9：初期リストは3件のまま', INITIAL_PRODUCTS.length, 3);

const q9Lines: string[] = [`=== 在庫一覧（${q9Products.length}件） ===`];
for (const product of q9Products) {
  q9Lines.push(formatProductLine(product, categoryNameOf(product.categoryId)));
}
q9Lines.push(`=== 検索「の」（${q9Found.length}件） ===`);
for (const product of q9Found) {
  q9Lines.push(`${product.name}（${product.price}円）`);
}
q9Lines.push('=== 在庫金額 ===');
q9Lines.push(
  `販売可能 ${q9Sellable.length}件 / 在庫切れ ${q9SoldOut.length}件 / ` +
    `在庫金額の合計 ${formatYen(calcTotalStockValue(q9Products))}`
);
q9Lines.push('=== 元のリスト ===');
q9Lines.push(
  `${INITIAL_PRODUCTS.length}件（${INITIAL_PRODUCTS.map((product) => product.name).join(', ')}）`
);

check(
  '問題9の出力',
  q9Lines.join('\n'),
  [
    '=== 在庫一覧（5件） ===',
    '[1] ラベンダーの石けん / バス・ボディケア /   480円 / 在庫 24個',
    '[2] ハンドクリーム / バス・ボディケア /  1800円 / 在庫 12個',
    '[3] マグカップ / キッチン雑貨 /  2350円 / 在庫  3個',
    '[4] リネンのふきん / ファブリック /   990円 / 在庫  0個（在庫切れ）',
    '[5] コットンのトートバッグ / ファブリック /  2800円 / 在庫  5個',
    '=== 検索「の」（3件） ===',
    'ラベンダーの石けん（480円）',
    'リネンのふきん（990円）',
    'コットンのトートバッグ（2800円）',
    '=== 在庫金額 ===',
    '販売可能 4件 / 在庫切れ 1件 / 在庫金額の合計 54,170円',
    '=== 元のリスト ===',
    '3件（ラベンダーの石けん, ハンドクリーム, マグカップ）',
  ].join('\n')
);

console.log('review01: ok');
