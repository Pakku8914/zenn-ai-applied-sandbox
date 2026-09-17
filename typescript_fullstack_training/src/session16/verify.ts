// セッション16「モジュール・tsconfig・null 安全」の検証スクリプト。
//
// 本文（057）と練習問題の解答（059）に載せたコードを実際に import して実行し、
// 章に書いた「期待される出力」と一致するかを確認する。
// 1つでも一致しなければ非0で終了する。
//
// この章はモジュール分割が主題なので、ロジックは同じフォルダの
// types / constants / shop-data / cart / pricing / parse / report に分けてある。
// 練習問題の解答コードは practice フォルダに置いた。
//
// 実行: docker compose exec ts npx tsx src/session16/verify.ts

import { describeLine, findProductById, isWithinQuantityLimit, toCartLines } from './cart';
import { DISCOUNT_PERCENT_BY_RANK, MAX_CART_QUANTITY, TAX_RATE } from './constants';
import { isProduct, parseJson, toProduct } from './parse';
import {
  buildPaymentSummary,
  calcDiscountAmount,
  calcShippingFee,
  calcSubtotal,
  calcTax,
  resolveDiscountRule,
} from './pricing';
import { buildReport } from './report';
import { brokenCartItems, cartItems, products } from './shop-data';
import type { CartLine, MemberRank, Product } from './types';

import { buildStockReport, formatStockReport } from './practice/q1-stock';
import { describeCatalog } from './practice/q2-report';
import { campaignPercent, campaignPercentBad, formatNullSafety } from './practice/q3-null-safe';
import { collectValidProducts, formatParseResult, toProducts } from './practice/q4-parse-products';
import {
  CATEGORY_LABEL,
  categoryLabelOf,
  formatCategoryReport,
} from './practice/q5-category-labels';
import { formatOrder } from './practice/q6-format';
import { SAMPLE_ORDER, calcOrderTotal } from './practice/q6-order';
import { INVALID_ORDER_JSON, SAMPLE_ORDER_JSON, toOrderRequest } from './practice/q7-input';
import { buildReceipt, buildReceiptText } from './practice/q7-receipt';

// ---------------------------------------------------------------------------
// 検証ヘルパー（期待値と違えば失敗として記録する）
// ---------------------------------------------------------------------------
let failedCount = 0;

function checkNumber(label: string, actual: number, expected: number): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

function checkString(label: string, actual: string, expected: string): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 "${expected}" / 実際 "${actual}"`);
    failedCount += 1;
  }
}

function checkBoolean(label: string, actual: boolean, expected: boolean): void {
  if (actual !== expected) {
    console.error(`NG: ${label} — 期待値 ${expected} / 実際 ${actual}`);
    failedCount += 1;
  }
}

// ---------------------------------------------------------------------------
// 本文 2節：分割したモジュールが import で正しくつながっている
// ---------------------------------------------------------------------------
const lines: CartLine[] = toCartLines(cartItems);

checkNumber('本文2節: 商品マスタの件数', products.length, 5);
checkNumber('本文2節: カート明細の件数', lines.length, 2);
checkString(
  '本文2節: describeLine の出力',
  lines.map((line) => describeLine(line)).join('\n'),
  'ラベンダーの石けん × 2点 = 960円\nマグカップ × 1点 = 2350円'
);

const mug = findProductById(3);
checkString('本文2節: findProductById(3)', mug === undefined ? '(なし)' : mug.name, 'マグカップ');
checkBoolean('本文2節: findProductById(99) は undefined', findProductById(99) === undefined, true);

// export していない値は import できない（型チェックで守られる）ため、
// ここでは「export したものが期待どおり動く」ことだけを確認する。
checkNumber('本文2節: 数量上限の定数', MAX_CART_QUANTITY, 10);
const firstLine = lines[0];
checkBoolean(
  '本文2節: 数量が上限内',
  firstLine === undefined ? false : isWithinQuantityLimit(firstLine),
  true
);

// ---------------------------------------------------------------------------
// 本文 7節：計算手順（小計 → 割引 → 税 → 送料 → 支払総額）
// ---------------------------------------------------------------------------
checkNumber('本文7節 手順1 小計', calcSubtotal(lines), 3310);
checkNumber('本文7節 手順2 割引額（silver 5%）', calcDiscountAmount(3310, 5), 165);
checkNumber('本文7節 手順4 消費税', calcTax(3145), 314);
checkNumber('本文7節 手順6 送料', calcShippingFee(3459), 0);
checkNumber('本文7節: 税率', TAX_RATE, 0.1);

const silverSummary = buildPaymentSummary(lines, resolveDiscountRule('silver'));
checkNumber('本文7節 手順7 支払総額（silver）', silverSummary.payableAmount, 3459);

// 送料がかかるケース（税込商品合計が 3000 円未満）
const soapOnly: CartLine[] = lines.filter((line) => line.product.id === 1);
const noneSummary = buildPaymentSummary(soapOnly, resolveDiscountRule('none'));
checkNumber('本文7節: 石けんだけの小計', noneSummary.subtotal, 960);
checkNumber('本文7節: 石けんだけの消費税', noneSummary.tax, 96);
checkNumber('本文7節: 石けんだけの送料', noneSummary.shippingFee, 500);
checkNumber('本文7節: 石けんだけの支払総額', noneSummary.payableAmount, 1556);

// noUncheckedIndexedAccess の効き（型は Product | undefined になる）
const outOfRange = products[10];
checkBoolean('本文7節: 範囲外の添字は undefined', outOfRange === undefined, true);

// ---------------------------------------------------------------------------
// 本文 8節：main.ts の出力（?. と ?? を含む）
// ---------------------------------------------------------------------------
checkString(
  '本文8節: buildReport("silver") の出力13行',
  buildReport('silver'),
  '--- カートの明細 ---\n' +
    'ラベンダーの石けん × 2点 = 960円\n' +
    'マグカップ × 1点 = 2350円\n' +
    '--- お支払い ---\n' +
    '小計: 3310円\n' +
    '割引: -165円\n' +
    '消費税: 314円\n' +
    '送料: 0円\n' +
    'お支払総額: 3459円\n' +
    '--- 欠けた値の扱い ---\n' +
    '先頭の明細: ラベンダーの石けん\n' +
    '商品が消えた明細を除いた件数: 1件\n' +
    'JSON から復元: マグカップ\n' +
    '壊れた JSON: (形が違います)'
);

// 商品が削除された明細は落ちる
checkNumber('本文8節: 壊れたカートは1件だけ残る', toCartLines(brokenCartItems).length, 1);

// ---------------------------------------------------------------------------
// 本文 9節：any は検査されない（Bad）／unknown は絞り込まないと使えない（Good）
// ---------------------------------------------------------------------------
const MUG_JSON = '{"id":3,"name":"マグカップ","price":2350,"stock":3,"categoryId":2}';

// Bad の実演：JSON.parse は any を返すので、タイポしても型エラーにならない
const parsedAsAny = JSON.parse(MUG_JSON);
checkString('本文9節 Bad: any はタイポを通す', `${parsedAsAny.nmae}`, 'undefined');

// Good：unknown で受けて型ガードで絞り込む
const parsedAsUnknown: unknown = parseJson(MUG_JSON);
checkBoolean('本文9節 Good: isProduct が true', isProduct(parsedAsUnknown), true);
checkBoolean('本文9節 Good: 文字列は Product ではない', isProduct('マグカップ'), false);
checkBoolean('本文9節 Good: null は Product ではない', isProduct(null), false);
checkBoolean(
  '本文9節 Good: price が文字列なら Product ではない',
  isProduct({ id: 3, name: 'マグカップ', price: '2350', stock: 3, categoryId: 2 }),
  false
);

const restored = toProduct(MUG_JSON);
checkString(
  '本文9節: toProduct で復元した商品名',
  restored === undefined ? '(形が違います)' : restored.name,
  'マグカップ'
);

// ---------------------------------------------------------------------------
// 本文 10節：as は実行時に何もしない／satisfies は推論を保つ
// ---------------------------------------------------------------------------
const fakeProduct = {} as Product; // 型チェックは通るが中身は空
checkString('本文10節: as で作った偽の Product', `${fakeProduct.name}`, 'undefined');

// 型注釈（Record<string, number>）ではキーのタイポを検出できない
const ratesAnnotated: Record<string, number> = { gold: 10, silver: 5, bronze: 3, none: 0 };
checkString('本文10節: 注釈だとタイポが undefined になる', `${ratesAnnotated['glod']}`, 'undefined');

// satisfies + as const なので、値はリテラル型のまま保たれる
checkNumber('本文10節: gold の割引率', DISCOUNT_PERCENT_BY_RANK.gold, 10);
checkNumber('本文10節: none の割引率', DISCOUNT_PERCENT_BY_RANK.none, 0);

const ranks: readonly MemberRank[] = ['gold', 'silver', 'bronze', 'none'];
checkString(
  '本文10節: 全ランクの割引率',
  ranks.map((rank) => `${rank}=${DISCOUNT_PERCENT_BY_RANK[rank]}`).join(' / '),
  'gold=10 / silver=5 / bronze=3 / none=0'
);

// ---------------------------------------------------------------------------
// 問題1：1ファイルを4つに分ける（在庫レポート）
// ---------------------------------------------------------------------------
checkString(
  '問題1: 在庫レポートの出力3行',
  formatStockReport(buildStockReport(products)),
  '在庫金額の合計: 54170円\n' +
    '在庫切れ: リネンのふきん\n' +
    '在庫わずか（5点以下）: マグカップ / コットンのトートバッグ'
);

// 在庫金額の内訳（解答の表に書いた数値）
checkNumber('問題1: 石けんの在庫金額', 480 * 24, 11520);
checkNumber('問題1: ハンドクリームの在庫金額', 1800 * 12, 21600);
checkNumber('問題1: マグカップの在庫金額', 2350 * 3, 7050);
checkNumber('問題1: ふきんの在庫金額', 990 * 0, 0);
checkNumber('問題1: トートバッグの在庫金額', 2800 * 5, 14000);
checkNumber('問題1: 合計', 11520 + 21600 + 7050 + 0 + 14000, 54170);

// 空の配列でも落ちない（別解の裏付け）
checkString(
  '問題1: 空配列のレポート',
  formatStockReport(buildStockReport([])),
  '在庫金額の合計: 0円\n在庫切れ: (なし)\n在庫わずか（5点以下）: (なし)'
);

// ---------------------------------------------------------------------------
// 問題2：窓口（バレル）ファイル経由で値と型を取り込む
// ---------------------------------------------------------------------------
checkString(
  '問題2: カタログの出力4行',
  describeCatalog(),
  '取り扱い商品: 5件\n' +
    '先頭: ラベンダーの石けん（480円 / 在庫24点）\n' +
    'id=3: マグカップ（2350円 / 在庫3点）\n' +
    'id=99: (なし)'
);

// ---------------------------------------------------------------------------
// 問題3：?. と ??（|| との違い）
// ---------------------------------------------------------------------------
checkString(
  '問題3: null 安全の出力10行',
  formatNullSafety(lines),
  'id=1 の商品名: ラベンダーの石けん\n' +
    'id=99 の商品名: (不明な商品)\n' +
    'id=1 の商品名の文字数: 9\n' +
    'id=99 の商品名の文字数: 0\n' +
    '先頭の明細: ラベンダーの石けん\n' +
    '空のカートの先頭: (カートは空です)\n' +
    'silver のキャンペーン割引（?? 版）: 0%\n' +
    'silver のキャンペーン割引（|| 版）: 5%\n' +
    'bronze のキャンペーン割引（?? 版）: 3%\n' +
    'gold のキャンペーン割引（?? 版）: 15%'
);

// || が 0 を潰すことの裏付け
checkNumber('問題3: ?? 版は意図した 0 を残す', campaignPercent('silver'), 0);
checkNumber('問題3: || 版は 0 を既定値に置き換える', campaignPercentBad('silver'), 5);
checkNumber('問題3: 未設定のランクは既定値', campaignPercent('none'), 0);

// ---------------------------------------------------------------------------
// 問題4：unknown で受けた JSON 配列を絞り込む
// ---------------------------------------------------------------------------
checkString(
  '問題4: パース結果の出力5行',
  formatParseResult(),
  '正しい配列: 2件\n' +
    '一部が壊れた配列: (形が違います)\n' +
    '配列でない JSON: (形が違います)\n' +
    '壊れた要素を除いた件数: 1件\n' +
    '救えた商品: ラベンダーの石けん'
);

checkBoolean('問題4: 空配列は Product[] として通る', toProducts('[]')?.length === 0, true);
checkNumber('問題4: 全部壊れていれば0件', collectValidProducts('[{"id":1}]').length, 0);

// ---------------------------------------------------------------------------
// 問題5：satisfies でカテゴリのマスタを守る
// ---------------------------------------------------------------------------
checkString(
  '問題5: カテゴリ別レポートの出力4行',
  formatCategoryReport(),
  'バス・ボディケア: ラベンダーの石けん / ハンドクリーム\n' +
    'キッチン雑貨: マグカップ\n' +
    'ファブリック: リネンのふきん / コットンのトートバッグ\n' +
    'categoryId=9: (不明なカテゴリ)'
);

checkString('問題5: as const で値はリテラルのまま', CATEGORY_LABEL.kitchen, 'キッチン雑貨');
checkString('問題5: 存在しない categoryId', categoryLabelOf(9), '(不明なカテゴリ)');
checkString('問題5: categoryId=1', categoryLabelOf(1), 'バス・ボディケア');

// ---------------------------------------------------------------------------
// 問題6：循環参照を解消した3ファイル構成
// ---------------------------------------------------------------------------
checkString(
  '問題6: 注文の整形結果5行',
  formatOrder(SAMPLE_ORDER),
  '=== 注文確認書 ===\n' +
    '注文 #1001\n' +
    'ラベンダーの石けん × 2点 = 960円\n' +
    'マグカップ × 1点 = 2350円\n' +
    '合計 3310円（3点）'
);

checkNumber('問題6: 注文合計', calcOrderTotal(SAMPLE_ORDER), 3310);

// ---------------------------------------------------------------------------
// 問題7：JSON → 検証 → カート → 金額 → 確認書
// ---------------------------------------------------------------------------
checkString(
  '問題7: 確認書の出力9行',
  buildReceiptText(SAMPLE_ORDER_JSON),
  '=== 注文確認書 ===\n' +
    'ハンドクリーム × 1点 = 1800円\n' +
    'コットンのトートバッグ × 1点 = 2800円\n' +
    '取り扱いのない商品を除外しました: productId=99\n' +
    '小計: 4600円\n' +
    '割引（gold）: -460円\n' +
    '消費税: 414円\n' +
    '送料: 0円\n' +
    'お支払総額: 4554円'
);

checkString(
  '問題7: rank が不正な入力',
  buildReceiptText(INVALID_ORDER_JSON),
  '(入力の形が正しくありません)'
);

checkString(
  '問題7: items が配列でない入力',
  buildReceiptText('{"rank":"gold","items":"none"}'),
  '(入力の形が正しくありません)'
);

checkString(
  '問題7: 明細が壊れている入力',
  buildReceiptText('{"rank":"gold","items":[{"productId":"2","quantity":1}]}'),
  '(入力の形が正しくありません)'
);

// 支払総額の内訳（解答の表に書いた数値）
const goldRequest = toOrderRequest(SAMPLE_ORDER_JSON);
if (goldRequest === undefined) {
  console.error('NG: 問題7 — SAMPLE_ORDER_JSON の検証に失敗しました');
  failedCount += 1;
} else {
  const receipt = buildReceipt(goldRequest);
  checkNumber('問題7 手順1 小計', receipt.summary.subtotal, 4600);
  checkNumber('問題7 手順2 割引額（gold 10%）', receipt.summary.discountAmount, 460);
  checkNumber('問題7 手順3 割引後小計', receipt.summary.discountedTotal, 4140);
  checkNumber('問題7 手順4 消費税', receipt.summary.tax, 414);
  checkNumber('問題7 手順5 税込商品合計', receipt.summary.totalWithTax, 4554);
  checkNumber('問題7 手順6 送料', receipt.summary.shippingFee, 0);
  checkNumber('問題7 手順7 支払総額', receipt.summary.payableAmount, 4554);
  checkNumber('問題7: 除外された商品の件数', receipt.skippedProductIds.length, 1);
  checkNumber('問題7: 明細の件数', receipt.lines.length, 2);
}

// ---------------------------------------------------------------------------
// 結果
// ---------------------------------------------------------------------------
if (failedCount > 0) {
  console.error(`session16: ${failedCount} 件の検証に失敗しました`);
  process.exit(1);
}

console.log('session16: ok');
