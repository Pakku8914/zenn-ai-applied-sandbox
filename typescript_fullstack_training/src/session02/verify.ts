/**
 * セッション2「演算子と文字列」のコード例と練習問題の解答を検証する。
 * 期待値と一致しなければエラー終了する。
 */

/** 比較できる値（== の暗黙変換を避けるため、比較は常に !== で行う） */
type Comparable = string | number | boolean;

/** 期待値と一致しなければメッセージを表示してエラー終了する */
const check = (label: string, actual: Comparable, expected: Comparable): void => {
  if (actual !== expected) {
    console.error(`[NG] ${label}: 期待値 ${String(expected)} / 実際 ${String(actual)}`);
    process.exit(1);
  }
};

// 本書の共通ルール（requirements.md の共通シナリオで固定）
const TAX_RATE = 0.1; // 消費税率10%
const SHIPPING_FEE = 500; // 送料（円）
const FREE_SHIPPING_THRESHOLD = 3000; // この金額以上で送料無料（円）

// ---------------------------------------------------------------------------
// 1. 算術演算子（本文「1. 算術演算子で計算する」）
// ---------------------------------------------------------------------------
check('50 / 8 は小数になる', 50 / 8, 6.25);
check('Math.floor(50 / 8)', Math.floor(50 / 8), 6);
check('50 % 8', 50 % 8, 2);
check('23 / 6 の表示', String(23 / 6), '3.8333333333333335');
check('Math.floor(23 / 6)', Math.floor(23 / 6), 3);
check('23 % 6', 23 % 6, 5);
check('7 / 2 は 3 ではない', 7 / 2, 3.5);
check('剰余の符号は左側に従う', -7 % 3, -1);
check('2 ** 10', 2 ** 10, 1024);
check('優先順位（かけ算が先）', 2 + 3 * 4, 14);
check('優先順位（カッコが最優先）', (2 + 3) * 4, 20);
check('Math.floor(-7 / 2)', Math.floor(-7 / 2), -4);
check('Math.trunc(-7 / 2)', Math.trunc(-7 / 2), -3);
check('Math.round(-7 / 2)', Math.round(-7 / 2), -3);
check('Math.ceil(-7 / 2)', Math.ceil(-7 / 2), -3);

// 0 除算はエラーにならず特別な値になる
check('10 / 0 は Infinity', 10 / 0, Infinity);
check('-10 / 0 は -Infinity', -10 / 0, -Infinity);
check('0 / 0 は NaN', Number.isNaN(0 / 0), true);

// ---------------------------------------------------------------------------
// 2. 浮動小数点誤差（本文「2. 小数の落とし穴と『金額は整数の円』ルール」）
//    本書の「金額は整数の円で扱う」ルールの根拠。ここが崩れたら本文を直す。
// ---------------------------------------------------------------------------
check('0.1 + 0.2 は 0.3 と等しくない', 0.1 + 0.2 === 0.3, false);
check('0.1 + 0.2 の表示', String(0.1 + 0.2), '0.30000000000000004');
check('0.1 + 0.2 と 0.3 の差は極小', Math.abs(0.1 + 0.2 - 0.3) < 1e-15, true);

// 複合代入で足し込んでも同じ誤差が出る
let accumulated = 0;
accumulated += 0.1;
accumulated += 0.1;
accumulated += 0.1;
check('0.1 を3回足した値', String(accumulated), '0.30000000000000004');

check('1 + TAX_RATE は 1.1 と等しい', 1 + TAX_RATE, 1.1);
check('1800 * (1 + TAX_RATE) の生の値', String(1800 * (1 + TAX_RATE)), '1980.0000000000002');
check('1800 * 1.1 も同じ値になる', String(1800 * 1.1), '1980.0000000000002');
check('Math.floor で整数の円になる', Math.floor(1800 * (1 + TAX_RATE)), 1980);
check('480 の税込（誤差の出ない値）', Math.floor(480 * (1 + TAX_RATE)), 528);
check('2350 の税込', Math.floor(2350 * (1 + TAX_RATE)), 2585);
check('整数だけで計算しても結果は同じ', Math.floor((1800 * 110) / 100), 1980);
check('Number.MAX_SAFE_INTEGER', Number.MAX_SAFE_INTEGER, 9007199254740991);

// ---------------------------------------------------------------------------
// 3. 複合代入とインクリメント（本文「3. 複合代入とインクリメント」）
// ---------------------------------------------------------------------------
let stock = 10;
stock += 5;
check('stock += 5', stock, 15);
stock -= 3;
check('stock -= 3', stock, 12);
stock++;
check('stock++', stock, 13);
stock--;
check('stock--', stock, 12);

let n = 5;
const postfixValue = n++; // 後置：先に 5 を渡してから増える
const prefixValue = ++n; // 前置：先に増えてから渡す
check('後置インクリメントの式の値', postfixValue, 5);
check('前置インクリメントの式の値', prefixValue, 7);
check('2回増やしたあとの n', n, 7);

let message = 'ハンド';
message += 'クリーム';
check('文字列にも += は使える', message, 'ハンドクリーム');

// ---------------------------------------------------------------------------
// 4. 比較演算子と厳密等価（本文「4. 比較演算子と厳密等価（===）」）
// ---------------------------------------------------------------------------
// 本文の比較演算子の表（計算結果の変数と基準値をくらべる）
const compareTotal = 1800 * 2; // 計算結果なので型は number（3600 というリテラル型にはならない）
check('total > 3000', compareTotal > 3000, true);
check('total >= 3600', compareTotal >= 3600, true);
check('total < 3000', compareTotal < 3000, false);
check('total <= 3000', compareTotal <= 3000, false);
check('total === 3600', compareTotal === 3600, true);
check('total !== 3000', compareTotal !== 3000, true);

check('3960 は 3000 以上', 3960 >= FREE_SHIPPING_THRESHOLD, true);
check('2640 は 3000 以上ではない', 2640 >= FREE_SHIPPING_THRESHOLD, false);
check('ちょうど 3000 も「以上」に含まれる', 3000 >= FREE_SHIPPING_THRESHOLD, true);
check('Math.max で下限 0 を作る（超過時）', Math.max(0, FREE_SHIPPING_THRESHOLD - 3960), 0);
check('Math.max で下限 0 を作る（不足時）', Math.max(0, FREE_SHIPPING_THRESHOLD - 2640), 360);

// == が true にしてしまう組み合わせを、明示変換して確認する
check("Number('') は 0", Number(''), 0);
check("Number('0') は 0", Number('0'), 0);
check("Number(' 42 ') は 42（前後の空白は無視される）", Number(' 42 '), 42);
check("Number('abc') は NaN", Number.isNaN(Number('abc')), true);
check("Number('1,800') は NaN", Number.isNaN(Number('1,800')), true);
check('カンマを除けば数値になる', Number('1,800'.replaceAll(',', '')), 1800);
check('NaN === NaN は false', Number.NaN === Number.NaN, false);

// 文字列の大小比較は文字コード順
check("'apple' < 'banana'", 'apple' < 'banana', true);
check("'あ' < 'い'", 'あ' < 'い', true);
check("'B' < 'a'（大文字が先）", 'B' < 'a', true);
check("'10' < '9'（文字列比較の罠）", '10' < '9', true);
check('数値に変換すれば正しく比べられる', Number('10') < Number('9'), false);

// ---------------------------------------------------------------------------
// 5. 論理演算子と短絡評価（本文「5. 論理演算子と短絡評価」）
// ---------------------------------------------------------------------------
const logicalStock = 12;
const logicalOrderQuantity = 2;
const logicalIsPublished = true;

check(
  '公開中かつ在庫が注文数以上',
  logicalIsPublished && logicalStock >= logicalOrderQuantity,
  true
);
const logicalIsSoldOut = logicalStock <= 0;
check('売り切れ判定', logicalIsSoldOut, false);
check('ボタンを隠すか', logicalIsSoldOut || !logicalIsPublished, false);

// 短絡評価：左が偽なら右は評価されない
let checkedCount = 0;
const hasStock = false;
const shortCircuitResult1 = hasStock && (checkedCount += 1) > 0;
check('&& の左が偽のときの結果', shortCircuitResult1, false);
check('&& の左が偽なら右は評価されない', checkedCount, 0);
const shortCircuitResult2 = logicalIsPublished && (checkedCount += 1) > 0;
check('&& の左が真のときの結果', shortCircuitResult2, true);
check('&& の左が真なら右が評価される', checkedCount, 1);

// && と || はオペランドの値そのものを返す
const inputName = '';
const truthyText = 'abc';
check('|| は falsy のとき右側を返す', inputName || '名称未設定', '名称未設定');
check('&& は左が truthy なら右側を返す', truthyText && 0, 0);
check("Boolean('')", Boolean(''), false);
check("Boolean('0') は true", Boolean('0'), true);
check('Boolean(0)', Boolean(0), false);
check('Boolean(NaN)', Boolean(Number.NaN), false);

// ---------------------------------------------------------------------------
// 6. テンプレートリテラルと文字列メソッド（本文「6.」）
// ---------------------------------------------------------------------------
const rawCode = '  sku-1234  ';
const code = rawCode.trim().toUpperCase();
check('trim + toUpperCase', code, 'SKU-1234');
check('length はカッコを付けない', code.length, 8);
check('slice(0, 3)', code.slice(0, 3), 'SKU');
check('slice(4)', code.slice(4), '1234');
check('slice(-4)', code.slice(-4), '1234');
check('includes', code.includes('SKU'), true);
check('startsWith', code.startsWith('SKU-'), true);
check('toLowerCase', code.toLowerCase(), 'sku-1234');
check('元の文字列は変わらない（イミュータブル）', rawCode.length, 12);
check('全角スペースも trim される', '　ハンドクリーム　'.trim(), 'ハンドクリーム');
check('padStart で桁をそろえる', '7'.padStart(4, '0'), '0007');
check('replaceAll', '1,800'.replaceAll(',', ''), '1800');
check('日本語の length', 'ハンドクリーム'.length, 7);
check('絵文字の length は 2', '\u{1F44D}'.length, 2);
check('テンプレートリテラル', `${'ハンドクリーム'}は${1800}円です`, 'ハンドクリームは1800円です');
check('テンプレートリテラルの中で計算できる', `小計：${1800 * 2}円`, '小計：3600円');

// split は「区切られた並び」を返す。番号で取り出した値は string | undefined になる
const splitParts = 'ハンドクリーム,1800,12'.split(',');
check('split の項目数', splitParts.length, 3);
check('split の1つ目', `${splitParts[0]}`, 'ハンドクリーム');
check('split の2つ目を数値に変換', Number(splitParts[1]), 1800);

// ---------------------------------------------------------------------------
// 7. 本文「7. まとめの実例：レシートを組み立てる」（src/session02/receipt.ts）
// ---------------------------------------------------------------------------
const bodyProductName = 'ハンドクリーム';
const bodyUnitPrice = 1800;
const bodyQuantity = 2;
const bodySubtotal = bodyUnitPrice * bodyQuantity;
const bodyTotalWithTax = Math.floor(bodySubtotal * (1 + TAX_RATE));
const bodyIsFreeShipping = bodyTotalWithTax >= FREE_SHIPPING_THRESHOLD;
const bodyRemaining = Math.max(0, FREE_SHIPPING_THRESHOLD - bodyTotalWithTax);

check('レシート：小計', bodySubtotal, 3600);
check('レシート：税込', bodyTotalWithTax, 3960);
check('レシート：送料無料', bodyIsFreeShipping, true);
check('レシート：不足額', bodyRemaining, 0);
check('レシート1行目', `商品：${bodyProductName}`, '商品：ハンドクリーム');
check(
  'レシート2行目',
  `単価：${bodyUnitPrice}円 × ${bodyQuantity}点 = ${bodySubtotal}円`,
  '単価：1800円 × 2点 = 3600円'
);
check('レシート3行目', `税込：${bodyTotalWithTax}円`, '税込：3960円');
check('レシート4行目', `送料無料：${bodyIsFreeShipping}`, '送料無料：true');
check('レシート5行目', `送料無料まで：あと${bodyRemaining}円`, '送料無料まで：あと0円');
check(
  'レシート6行目',
  `（送料無料でない場合の送料：${SHIPPING_FEE}円）`,
  '（送料無料でない場合の送料：500円）'
);

// ---------------------------------------------------------------------------
// 8. 練習問題の解答（解答章の「期待される出力」と一致すること）
// ---------------------------------------------------------------------------

// 問題1：レシートの1行
const p1Subtotal = 480 * 3;
check(
  '問題1の出力',
  `ラベンダーの石けん ${480}円 × ${3}点 = ${p1Subtotal}円`,
  'ラベンダーの石けん 480円 × 3点 = 1440円'
);

// 問題2：箱詰めの計算
const p2Exact = 50 / 8;
check('問題2：そのまま割った値', `そのまま割った値：${p2Exact}`, 'そのまま割った値：6.25');
check('問題2：満杯の箱', `満杯の箱：${Math.floor(p2Exact)}箱`, '満杯の箱：6箱');
check('問題2：残り', `残り：${50 % 8}個`, '残り：2個');

// 問題3：税込価格
check('問題3：石けん', `石けん：${Math.floor(480 * (1 + TAX_RATE))}円`, '石けん：528円');
check(
  '問題3：ハンドクリーム',
  `ハンドクリーム：${Math.floor(1800 * (1 + TAX_RATE))}円`,
  'ハンドクリーム：1980円'
);
check('問題3：マグカップ', `マグカップ：${Math.floor(2350 * (1 + TAX_RATE))}円`, 'マグカップ：2585円');
check('問題3：誤差の行', `0.1 + 0.2 = ${0.1 + 0.2}`, '0.1 + 0.2 = 0.30000000000000004');
check(
  '問題3：比較の行',
  `0.1 + 0.2 === 0.3 は ${0.1 + 0.2 === 0.3}`,
  '0.1 + 0.2 === 0.3 は false'
);

// 問題4：送料無料まであといくら
const p4Subtotal = 480 * 5;
const p4TotalWithTax = Math.floor(p4Subtotal * (1 + TAX_RATE));
const p4IsFreeShipping = p4TotalWithTax >= FREE_SHIPPING_THRESHOLD;
const p4Remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - p4TotalWithTax);
let p4Payment = p4TotalWithTax;
p4Payment += SHIPPING_FEE;
check('問題4：税込合計', `税込合計：${p4TotalWithTax}円`, '税込合計：2640円');
check('問題4：送料無料', `送料無料：${p4IsFreeShipping}`, '送料無料：false');
check('問題4：不足額', `送料無料まで：あと${p4Remaining}円`, '送料無料まで：あと360円');
check('問題4：支払額', `送料を含めた支払額：${p4Payment}円`, '送料を含めた支払額：3140円');
check('問題4：別解も同じ値', p4TotalWithTax + SHIPPING_FEE, 3140);

// 問題5：商品コードの検査
const p5Code1 = '  sku-0042  '.trim().toUpperCase();
const p5Code2 = ' abc-42 '.trim().toUpperCase();
const p5IsValid1 = p5Code1.startsWith('SKU-') && p5Code1.length === 8;
const p5IsValid2 = p5Code2.startsWith('SKU-') && p5Code2.length === 8;
check('問題5：コード1', `コード1：${p5Code1}（${p5Code1.length}文字）`, 'コード1：SKU-0042（8文字）');
check('問題5：コード1は有効', `コード1は有効：${p5IsValid1}`, 'コード1は有効：true');
check(
  '問題5：分類と連番',
  `コード1の分類：${p5Code1.slice(0, 3)} / 連番：${p5Code1.slice(-4)}`,
  'コード1の分類：SKU / 連番：0042'
);
check('問題5：コード2', `コード2：${p5Code2}（${p5Code2.length}文字）`, 'コード2：ABC-42（6文字）');
check('問題5：コード2は無効', `コード2は有効：${p5IsValid2}`, 'コード2は有効：false');

// 問題6：CSV の1行を分解
const p6Parts = 'ラベンダーの石けん,480,3'.split(',');
const p6UnitPrice = Number(p6Parts[1]);
const p6Quantity = Number(p6Parts[2]);
const p6Subtotal = p6UnitPrice * p6Quantity;
check('問題6：項目数', `項目数：${p6Parts.length}`, '項目数：3');
check(
  '問題6：明細行',
  `${p6Parts[0]}：${p6UnitPrice}円 × ${p6Quantity}点`,
  'ラベンダーの石けん：480円 × 3点'
);
check('問題6：小計', `小計：${p6Subtotal}円`, '小計：1440円');
check('問題6：税込', `税込：${Math.floor(p6Subtotal * (1 + TAX_RATE))}円`, '税込：1584円');

const p6BrokenParts = 'マグカップ,2350'.split(',');
const p6BrokenQuantity = Number(p6BrokenParts[2]); // Number(undefined) は NaN
const p6BrokenSubtotal = Number(p6BrokenParts[1]) * p6BrokenQuantity;
check('問題6：壊れた行の項目数', `項目数：${p6BrokenParts.length}`, '項目数：2');
check(
  '問題6：数量を取り出せたか',
  `数量を数値として取り出せたか：${!Number.isNaN(p6BrokenQuantity)}`,
  '数量を数値として取り出せたか：false'
);
check('問題6：壊れた行の小計', `小計：${p6BrokenSubtotal}円`, '小計：NaN円');

// 問題7：注文明細の組み立て
const P7_SEPARATOR = '------------------------'; // ハイフン24個
const p7Subtotal = 480 * 1 + 1800 * 1;
const p7TotalWithTax = Math.floor(p7Subtotal * (1 + TAX_RATE));
const p7IsFreeShipping = p7TotalWithTax >= FREE_SHIPPING_THRESHOLD;
const p7ShippingFee = Number(!p7IsFreeShipping) * SHIPPING_FEE;
const p7Payment = p7TotalWithTax + p7ShippingFee;
const p7Remaining = Math.max(0, FREE_SHIPPING_THRESHOLD - p7TotalWithTax);

check('問題7：税抜合計', p7Subtotal, 2280);
check('問題7：税込合計', p7TotalWithTax, 2508);
check('問題7：送料（無料ではない）', p7ShippingFee, 500);
check('問題7：お支払金額', p7Payment, 3008);
check('問題7：不足額', p7Remaining, 492);
check('問題7：区切り線は24文字', P7_SEPARATOR.length, 24);
check('問題7：repeat 版と一致する', '-'.repeat(24), P7_SEPARATOR);

const p7Receipt = `=== ご注文明細 ===
ラベンダーの石けん × 1点: ${String(480).padStart(6, ' ')}円
ハンドクリーム × 1点: ${String(1800).padStart(6, ' ')}円
${P7_SEPARATOR}
商品合計（税抜）: ${String(p7Subtotal).padStart(6, ' ')}円
商品合計（税込）: ${String(p7TotalWithTax).padStart(6, ' ')}円
送料: ${String(p7ShippingFee).padStart(6, ' ')}円
お支払金額: ${String(p7Payment).padStart(6, ' ')}円
送料無料まであと: ${String(p7Remaining).padStart(6, ' ')}円`;

check('問題7：明細は9行', p7Receipt.split('\n').length, 9);
check('問題7：商品行（480円）', 'ラベンダーの石けん × 1点:    480円', `ラベンダーの石けん × 1点: ${String(480).padStart(6, ' ')}円`);
check('問題7：税込の行', '商品合計（税込）:   2508円', `商品合計（税込）: ${String(p7TotalWithTax).padStart(6, ' ')}円`);
check('問題7：送料の行', '送料:    500円', `送料: ${String(p7ShippingFee).padStart(6, ' ')}円`);

console.log('session02: ok');
