/**
 * 中間プロジェクト1「CLI 在庫管理ツール」の模範解答を検証する。
 *
 * import/export は Phase 4 まで未習のため、inventory.ts のセクション1〜10 を
 * このファイルにコピーしている（この重複はモジュール分割で解消できる）。
 * 期待値と一致しなければ非0終了する。
 */

// ===== 1. 定数 =====================================================

/** 在庫がこの数以下（かつ1以上）なら「残りわずか」と表示する */
const LOW_STOCK_THRESHOLD = 5;
/** 一覧の商品名の列幅（全角の商品名を前提にした簡易整形） */
const NAME_COLUMN_WIDTH = 12;
/** 一覧の単価の列幅（桁区切りを入れた文字数） */
const PRICE_COLUMN_WIDTH = 6;
/** 一覧の在庫数の列幅 */
const STOCK_COLUMN_WIDTH = 3;
/** 一覧の在庫金額の列幅 */
const VALUE_COLUMN_WIDTH = 7;

// ===== 2. 在庫データ ===============================================

/** 初期在庫。ミニ雑貨ショップのマスタから在庫管理に必要な3項目だけを取り出したもの */
const INITIAL_PRODUCTS: { name: string; price: number; stock: number }[] = [
  { name: 'ラベンダーの石けん', price: 480, stock: 24 },
  { name: 'ハンドクリーム', price: 1800, stock: 12 },
  { name: 'マグカップ', price: 2350, stock: 3 },
  { name: 'リネンのふきん', price: 990, stock: 0 },
  { name: 'コットンのトートバッグ', price: 2800, stock: 5 },
];

// ===== 3. 在庫金額の計算 ===========================================

/** 1商品の在庫金額（単価 × 在庫数） */
const calcStockValue = (product: { price: number; stock: number }): number =>
  product.price * product.stock;

// ===== 4. 金額と数量の整形 =========================================

/** 3桁ごとにカンマを入れる（11520 → "11,520"） */
const formatNumberWithComma = (value: number): string => {
  let rest = `${value}`;
  let grouped = '';
  while (rest.length > 3) {
    grouped = `,${rest.slice(rest.length - 3)}${grouped}`;
    rest = rest.slice(0, rest.length - 3);
  }
  return `${rest}${grouped}`;
};

/** 金額を「11,520円」の形にする */
const formatYen = (amount: number): string => `${formatNumberWithComma(amount)}円`;

/** 在庫状況のラベル。在庫0の判定を先に書くのが要点 */
const stockLabel = (stock: number): string => {
  if (stock === 0) {
    return '【在庫切れ】';
  }
  if (stock <= LOW_STOCK_THRESHOLD) {
    return '【残りわずか】';
  }
  return '';
};

// ===== 5. 合計の計算 ===============================================

/** 在庫金額の合計 */
const calcTotalStockValue = (
  products: { name: string; price: number; stock: number }[]
): number => products.reduce((total, product) => total + calcStockValue(product), 0);

/** 在庫の総点数 */
const calcTotalStock = (products: { name: string; price: number; stock: number }[]): number =>
  products.reduce((total, product) => total + product.stock, 0);

// ===== 6. 一覧表示 =================================================

/** 一覧の1行を組み立てる */
const formatProductLine = (
  index: number,
  product: { name: string; price: number; stock: number }
): string => {
  const name = product.name.padEnd(NAME_COLUMN_WIDTH);
  const price = formatNumberWithComma(product.price).padStart(PRICE_COLUMN_WIDTH);
  const stock = `${product.stock}`.padStart(STOCK_COLUMN_WIDTH);
  const value = formatNumberWithComma(calcStockValue(product)).padStart(VALUE_COLUMN_WIDTH);
  const label = stockLabel(product.stock);
  const suffix = label === '' ? '' : ` ${label}`;
  return `${index}. ${name} ${price}円 ×${stock}点 = ${value}円${suffix}`;
};

/** 在庫一覧のテキスト全体（複数行） */
const buildListText = (products: { name: string; price: number; stock: number }[]): string => {
  if (products.length === 0) {
    return '登録されている商品はありません。';
  }
  const lines: string[] = [`=== 在庫一覧（${products.length}件） ===`];
  let index = 1;
  for (const product of products) {
    lines.push(formatProductLine(index, product));
    index += 1;
  }
  lines.push(
    `合計 ${products.length}件 / 在庫 ${calcTotalStock(products)}点 / ` +
      `在庫金額 ${formatYen(calcTotalStockValue(products))}`
  );
  return lines.join('\n');
};

// ===== 7. 検索 =====================================================

/** 商品名の部分一致で検索する（大文字小文字は区別しない） */
const searchProductsByName = (
  products: { name: string; price: number; stock: number }[],
  keyword: string
): { name: string; price: number; stock: number }[] => {
  const normalized = keyword.trim().toLowerCase();
  if (normalized.length === 0) {
    return [];
  }
  return products.filter((product) => product.name.toLowerCase().includes(normalized));
};

/** 同じ名前の商品が登録済みかどうか */
const hasProductNamed = (
  products: { name: string; price: number; stock: number }[],
  name: string
): boolean => products.some((product) => product.name === name.trim());

/** 検索結果のテキスト */
const buildSearchText = (
  products: { name: string; price: number; stock: number }[],
  keyword: string
): string => {
  const found = searchProductsByName(products, keyword);
  if (found.length === 0) {
    return `「${keyword}」に一致する商品はありません。`;
  }
  const lines: string[] = [`=== 検索結果：「${keyword}」（${found.length}件） ===`];
  let index = 1;
  for (const product of found) {
    lines.push(formatProductLine(index, product));
    index += 1;
  }
  return lines.join('\n');
};

// ===== 8. 商品の追加 ===============================================

/** 入力値のバリデーション。失敗のときだけ message に理由が入る */
const validateProductInput = (
  products: { name: string; price: number; stock: number }[],
  name: string,
  price: number,
  stock: number
): { ok: boolean; message: string } => {
  if (name.trim().length === 0) {
    return { ok: false, message: '商品名を入力してください。' };
  }
  if (hasProductNamed(products, name)) {
    return { ok: false, message: `「${name.trim()}」はすでに登録されています。` };
  }
  if (Number.isNaN(price) || price < 1 || Math.floor(price) !== price) {
    return { ok: false, message: '単価は1以上の整数（円）で入力してください。' };
  }
  if (Number.isNaN(stock) || stock < 0 || Math.floor(stock) !== stock) {
    return { ok: false, message: '在庫数は0以上の整数で入力してください。' };
  }
  return { ok: true, message: '' };
};

/** 商品を追加する。元の配列は変えず、新しい配列を返す */
const addProduct = (
  products: { name: string; price: number; stock: number }[],
  name: string,
  price: number,
  stock: number
): {
  ok: boolean;
  message: string;
  products: { name: string; price: number; stock: number }[];
} => {
  const validated = validateProductInput(products, name, price, stock);
  if (!validated.ok) {
    return { ok: false, message: validated.message, products: products };
  }
  const newProduct = { name: name.trim(), price: price, stock: stock };
  return {
    ok: true,
    message: `「${newProduct.name}」を追加しました。（単価 ${formatYen(price)} / 在庫 ${stock}点）`,
    products: [...products, newProduct],
  };
};

// ===== 9. 集計 =====================================================

/** 平均単価（1円未満は切り捨て） */
const calcAveragePrice = (products: { name: string; price: number; stock: number }[]): number => {
  if (products.length === 0) {
    return 0;
  }
  const totalPrice = products.reduce((total, product) => total + product.price, 0);
  return Math.floor(totalPrice / products.length);
};

/** 商品名を " / " でつないだ文字列（0件なら "なし"） */
const joinProductNames = (products: { name: string; price: number; stock: number }[]): string => {
  if (products.length === 0) {
    return 'なし';
  }
  return products.map((product) => product.name).join(' / ');
};

/** 在庫サマリーのテキスト（複数行） */
const buildSummaryText = (products: { name: string; price: number; stock: number }[]): string => {
  if (products.length === 0) {
    return '登録されている商品はありません。';
  }
  const outOfStock = products.filter((product) => product.stock === 0);
  const lowStock = products.filter(
    (product) => product.stock > 0 && product.stock <= LOW_STOCK_THRESHOLD
  );
  const ranked = products.toSorted((a, b) => calcStockValue(b) - calcStockValue(a));
  const top = ranked[0];
  const topText = top === undefined ? 'なし' : `${top.name}（${formatYen(calcStockValue(top))}）`;
  const lines: string[] = [
    '=== 在庫サマリー ===',
    `商品数: ${products.length}件`,
    `在庫総数: ${calcTotalStock(products)}点`,
    `在庫金額合計: ${formatYen(calcTotalStockValue(products))}`,
    `在庫切れ: ${outOfStock.length}件（${joinProductNames(outOfStock)}）`,
    `残りわずか（${LOW_STOCK_THRESHOLD}点以下）: ${lowStock.length}件（${joinProductNames(lowStock)}）`,
    `平均単価: ${formatYen(calcAveragePrice(products))}`,
    `在庫金額トップ: ${topText}`,
  ];
  return lines.join('\n');
};

// ===== 10. コマンドの解釈 ==========================================

/** help で表示する行 */
const HELP_LINES: string[] = [
  '=== コマンド一覧 ===',
  'list                        在庫を一覧表示する',
  'search <キーワード>         商品名で部分一致検索する',
  'add <名前>,<単価>,<在庫数>  商品を追加する',
  'summary                     在庫の集計を表示する',
  'help                        このコマンド一覧を表示する',
  'quit                        終了する',
];

/** 入力1行を「コマンド名」と「引数」に分ける */
const parseCommand = (line: string): { name: string; argument: string } => {
  const parts = line.trim().split(' ');
  const head = parts[0] ?? '';
  const argument = parts.slice(1).join(' ').trim();
  return { name: head.toLowerCase(), argument: argument };
};

/** add の引数「名前,単価,在庫数」を分解する */
const parseAddArgument = (
  argument: string
): { ok: boolean; message: string; name: string; price: number; stock: number } => {
  const parts = argument.split(',');
  if (parts.length !== 3) {
    return {
      ok: false,
      message: 'add の引数は「名前,単価,在庫数」の3つをカンマ区切りで指定してください。',
      name: '',
      price: 0,
      stock: 0,
    };
  }
  return {
    ok: true,
    message: '',
    name: (parts[0] ?? '').trim(),
    price: Number((parts[1] ?? '').trim()),
    stock: Number((parts[2] ?? '').trim()),
  };
};

/** 1コマンドを処理する。画面出力はせず、出したい文字列を返す */
const runCommand = (
  products: { name: string; price: number; stock: number }[],
  line: string
): {
  products: { name: string; price: number; stock: number }[];
  output: string;
  quit: boolean;
} => {
  const command = parseCommand(line);
  switch (command.name) {
    case '':
      return { products: products, output: '', quit: false };
    case 'list':
      return { products: products, output: buildListText(products), quit: false };
    case 'search':
      if (command.argument === '') {
        return {
          products: products,
          output: 'search の後ろに検索キーワードを指定してください。（例: search マグ）',
          quit: false,
        };
      }
      return {
        products: products,
        output: buildSearchText(products, command.argument),
        quit: false,
      };
    case 'add': {
      const parsed = parseAddArgument(command.argument);
      if (!parsed.ok) {
        return { products: products, output: parsed.message, quit: false };
      }
      const added = addProduct(products, parsed.name, parsed.price, parsed.stock);
      return { products: added.products, output: added.message, quit: false };
    }
    case 'summary':
      return { products: products, output: buildSummaryText(products), quit: false };
    case 'help':
      return { products: products, output: HELP_LINES.join('\n'), quit: false };
    case 'quit':
      return { products: products, output: '終了します。', quit: true };
    default:
      return {
        products: products,
        output: `不明なコマンドです：${command.name}（help でコマンド一覧を表示します）`,
        quit: false,
      };
  }
};

/** コマンドの配列を順に処理する。画面出力はしない */
const runCommands = (
  initialProducts: { name: string; price: number; stock: number }[],
  commands: string[]
): { products: { name: string; price: number; stock: number }[]; logs: string[] } => {
  let products = initialProducts;
  const logs: string[] = [];
  for (const line of commands) {
    const result = runCommand(products, line);
    products = result.products;
    if (result.output !== '') {
      logs.push(result.output);
    }
    if (result.quit) {
      break;
    }
  }
  return { products: products, logs: logs };
};

/** 動作確認用のコマンド列（inventory.ts の画面出力セクションと同じ） */
const DEMO_COMMANDS: string[] = [
  'help',
  'list',
  'search の',
  'add 入浴剤,650,10',
  'add ラベンダーの石けん,480,5',
  'add ,100,1',
  'add タオル,1200',
  'summary',
  'stock',
  'quit',
  'list',
];

// ===== 12. 簡易アサーション ========================================

/** 失敗した検証の件数 */
let failureCount = 0;

/** 期待値と一致しなければ内容を表示して失敗件数を増やす */
const assertText = (label: string, actual: string, expected: string): void => {
  if (actual !== expected) {
    failureCount += 1;
    console.error(`[NG] ${label}`);
    console.error(`     期待値: ${expected}`);
    console.error(`     実際　: ${actual}`);
  }
};

/** 数値の比較（テンプレートリテラルで文字列にしてから比べる） */
const assertNumber = (label: string, actual: number, expected: number): void => {
  assertText(label, `${actual}`, `${expected}`);
};

/** true であることの確認 */
const assertTrue = (label: string, actual: boolean): void => {
  assertText(label, `${actual}`, 'true');
};

// ===== 13. 検証 ====================================================

// --- 課題1: データと在庫金額 ---------------------------------------
assertNumber('初期データの件数', INITIAL_PRODUCTS.length, 5);
assertNumber('石けんの在庫金額', calcStockValue({ price: 480, stock: 24 }), 11520);
assertNumber('ハンドクリームの在庫金額', calcStockValue({ price: 1800, stock: 12 }), 21600);
assertNumber('マグカップの在庫金額', calcStockValue({ price: 2350, stock: 3 }), 7050);
assertNumber('ふきんの在庫金額（在庫0）', calcStockValue({ price: 990, stock: 0 }), 0);
assertNumber('トートバッグの在庫金額', calcStockValue({ price: 2800, stock: 5 }), 14000);

// --- 課題2: 整形と合計 ---------------------------------------------
assertText('桁区切り（0）', formatNumberWithComma(0), '0');
assertText('桁区切り（480）', formatNumberWithComma(480), '480');
assertText('桁区切り（1000）', formatNumberWithComma(1000), '1,000');
assertText('桁区切り（11520）', formatNumberWithComma(11520), '11,520');
assertText('桁区切り（54170）', formatNumberWithComma(54170), '54,170');
assertText('桁区切り（1234567）', formatNumberWithComma(1234567), '1,234,567');
assertText('円表記', formatYen(54170), '54,170円');

assertText('在庫0のラベル', stockLabel(0), '【在庫切れ】');
assertText('在庫1のラベル', stockLabel(1), '【残りわずか】');
assertText('在庫3のラベル', stockLabel(3), '【残りわずか】');
assertText('しきい値ちょうどのラベル', stockLabel(LOW_STOCK_THRESHOLD), '【残りわずか】');
assertText('しきい値を超えたラベル', stockLabel(LOW_STOCK_THRESHOLD + 1), '');
assertText('在庫24のラベル', stockLabel(24), '');

// 列幅（桁揃え）の確認
// 埋めた空白は数え間違えやすいので、- に置き換えてから比べる
assertText(
  '単価の列は右詰め',
  formatNumberWithComma(480).padStart(PRICE_COLUMN_WIDTH).replaceAll(' ', '-'),
  '---480'
);
assertText(
  '在庫の列は右詰め',
  `${0}`.padStart(STOCK_COLUMN_WIDTH).replaceAll(' ', '-'),
  '--0'
);
assertText(
  '在庫金額の列は右詰め',
  formatNumberWithComma(11520).padStart(VALUE_COLUMN_WIDTH).replaceAll(' ', '-'),
  '-11,520'
);
assertText(
  '商品名の列は左詰め',
  'マグカップ'.padEnd(NAME_COLUMN_WIDTH).replaceAll(' ', '-'),
  'マグカップ-------'
);

assertNumber('在庫金額合計', calcTotalStockValue(INITIAL_PRODUCTS), 54170);
assertNumber('在庫総数', calcTotalStock(INITIAL_PRODUCTS), 44);
assertNumber('0件の在庫金額合計', calcTotalStockValue([]), 0);

// 桁揃えの空白は数え間違えやすいので、空白を除いて内容だけを比べる
assertText(
  '1行の整形（空白を除いて比較）',
  formatProductLine(1, { name: 'マグカップ', price: 2350, stock: 3 }).replaceAll(' ', ''),
  '1.マグカップ2,350円×3点=7,050円【残りわずか】'
);
assertText(
  '一覧テキスト（空白を除いて比較）',
  buildListText(INITIAL_PRODUCTS).replaceAll(' ', ''),
  [
    '===在庫一覧（5件）===',
    '1.ラベンダーの石けん480円×24点=11,520円',
    '2.ハンドクリーム1,800円×12点=21,600円',
    '3.マグカップ2,350円×3点=7,050円【残りわずか】',
    '4.リネンのふきん990円×0点=0円【在庫切れ】',
    '5.コットンのトートバッグ2,800円×5点=14,000円【残りわずか】',
    '合計5件/在庫44点/在庫金額54,170円',
  ].join('\n')
);
assertText('0件の一覧', buildListText([]), '登録されている商品はありません。');

// --- 課題3: 検索 ---------------------------------------------------
assertNumber('「ハンド」の一致件数', searchProductsByName(INITIAL_PRODUCTS, 'ハンド').length, 1);
assertNumber('「の」の一致件数', searchProductsByName(INITIAL_PRODUCTS, 'の').length, 3);
assertNumber('「マグ」の一致件数', searchProductsByName(INITIAL_PRODUCTS, 'マグ').length, 1);
assertNumber('「タオル」の一致件数', searchProductsByName(INITIAL_PRODUCTS, 'タオル').length, 0);
assertNumber('空キーワードは0件', searchProductsByName(INITIAL_PRODUCTS, '   ').length, 0);
assertText(
  '「の」の検索結果（空白を除いて比較）',
  buildSearchText(INITIAL_PRODUCTS, 'の').replaceAll(' ', ''),
  [
    '===検索結果：「の」（3件）===',
    '1.ラベンダーの石けん480円×24点=11,520円',
    '2.リネンのふきん990円×0点=0円【在庫切れ】',
    '3.コットンのトートバッグ2,800円×5点=14,000円【残りわずか】',
  ].join('\n')
);
assertText(
  '0件の検索',
  buildSearchText(INITIAL_PRODUCTS, 'タオル'),
  '「タオル」に一致する商品はありません。'
);
assertTrue('登録済みの名前を検出する', hasProductNamed(INITIAL_PRODUCTS, 'マグカップ'));
assertText('未登録の名前', `${hasProductNamed(INITIAL_PRODUCTS, 'タオル')}`, 'false');

// --- 課題4: 追加と検証 ---------------------------------------------
const added = addProduct(INITIAL_PRODUCTS, '入浴剤', 650, 10);
assertTrue('追加が成功する', added.ok);
assertText(
  '追加成功のメッセージ',
  added.message,
  '「入浴剤」を追加しました。（単価 650円 / 在庫 10点）'
);
assertNumber('追加後の件数', added.products.length, 6);
assertNumber('元の配列の件数は変わらない', INITIAL_PRODUCTS.length, 5);
assertText('元の配列とは別の配列', `${added.products === INITIAL_PRODUCTS}`, 'false');
assertNumber('追加後の在庫金額合計', calcTotalStockValue(added.products), 60670);
assertNumber('追加後の在庫総数', calcTotalStock(added.products), 54);

const emptyName = addProduct(INITIAL_PRODUCTS, '   ', 100, 1);
assertText('空の名前は拒否', emptyName.message, '商品名を入力してください。');
assertText('失敗時は同じ配列を返す', `${emptyName.products === INITIAL_PRODUCTS}`, 'true');

assertText(
  '重複した名前は拒否',
  addProduct(INITIAL_PRODUCTS, 'ラベンダーの石けん', 480, 5).message,
  '「ラベンダーの石けん」はすでに登録されています。'
);
assertText(
  '単価0は拒否',
  addProduct(INITIAL_PRODUCTS, 'タオル', 0, 3).message,
  '単価は1以上の整数（円）で入力してください。'
);
assertText(
  '単価の小数は拒否',
  addProduct(INITIAL_PRODUCTS, 'タオル', 1200.5, 3).message,
  '単価は1以上の整数（円）で入力してください。'
);
assertText(
  '数値にできない単価は拒否',
  addProduct(INITIAL_PRODUCTS, 'タオル', Number('abc'), 3).message,
  '単価は1以上の整数（円）で入力してください。'
);
assertText(
  '負の在庫は拒否',
  addProduct(INITIAL_PRODUCTS, 'タオル', 1200, -1).message,
  '在庫数は0以上の整数で入力してください。'
);
assertText(
  '在庫0は受け付ける',
  addProduct(INITIAL_PRODUCTS, 'タオル', 1200, 0).message,
  '「タオル」を追加しました。（単価 1,200円 / 在庫 0点）'
);
assertTrue('検証だけを単体で呼べる', validateProductInput(INITIAL_PRODUCTS, 'タオル', 1200, 3).ok);

// --- 課題5: 集計 ---------------------------------------------------
assertNumber('平均単価', calcAveragePrice(INITIAL_PRODUCTS), 1684);
assertNumber('追加後の平均単価', calcAveragePrice(added.products), 1511);
assertNumber('0件の平均単価', calcAveragePrice([]), 0);
assertText(
  '在庫切れの商品名',
  joinProductNames(INITIAL_PRODUCTS.filter((product) => product.stock === 0)),
  'リネンのふきん'
);
assertText('0件の連結', joinProductNames([]), 'なし');
assertText(
  'サマリー（初期在庫）',
  buildSummaryText(INITIAL_PRODUCTS),
  [
    '=== 在庫サマリー ===',
    '商品数: 5件',
    '在庫総数: 44点',
    '在庫金額合計: 54,170円',
    '在庫切れ: 1件（リネンのふきん）',
    '残りわずか（5点以下）: 2件（マグカップ / コットンのトートバッグ）',
    '平均単価: 1,684円',
    '在庫金額トップ: ハンドクリーム（21,600円）',
  ].join('\n')
);
assertText(
  'サマリー（入浴剤を追加したあと）',
  buildSummaryText(added.products),
  [
    '=== 在庫サマリー ===',
    '商品数: 6件',
    '在庫総数: 54点',
    '在庫金額合計: 60,670円',
    '在庫切れ: 1件（リネンのふきん）',
    '残りわずか（5点以下）: 2件（マグカップ / コットンのトートバッグ）',
    '平均単価: 1,511円',
    '在庫金額トップ: ハンドクリーム（21,600円）',
  ].join('\n')
);
assertText('0件のサマリー', buildSummaryText([]), '登録されている商品はありません。');
// toSorted は元の配列を並べ替えない（サマリーを作ったあとも先頭は変わらない）
const firstProduct = INITIAL_PRODUCTS[0];
assertText(
  '並べ替えても先頭は石けんのまま',
  firstProduct === undefined ? '' : firstProduct.name,
  'ラベンダーの石けん'
);

// --- 課題6: コマンドの解釈 -----------------------------------------
assertText('大文字のコマンド', parseCommand('LIST').name, 'list');
assertText('引数なしの引数は空文字', parseCommand('list').argument, '');
assertText('検索コマンドの引数', parseCommand('search マグ').argument, 'マグ');
assertText('追加コマンドの引数', parseCommand('add 入浴剤,650,10').argument, '入浴剤,650,10');
assertText('前後の空白は無視', parseCommand('  summary  ').name, 'summary');
assertText('空行のコマンド名は空文字', parseCommand('').name, '');

const parsedAdd = parseAddArgument('入浴剤,650,10');
assertTrue('add 引数の解析が成功する', parsedAdd.ok);
assertText('add 引数の名前', parsedAdd.name, '入浴剤');
assertNumber('add 引数の単価', parsedAdd.price, 650);
assertNumber('add 引数の在庫数', parsedAdd.stock, 10);
assertText(
  '引数の数が違うとき',
  parseAddArgument('タオル,1200').message,
  'add の引数は「名前,単価,在庫数」の3つをカンマ区切りで指定してください。'
);

const unknownCommand = runCommand(INITIAL_PRODUCTS, 'stock');
assertText(
  '未知のコマンド',
  unknownCommand.output,
  '不明なコマンドです：stock（help でコマンド一覧を表示します）'
);
assertText('未知のコマンドでも終了しない', `${unknownCommand.quit}`, 'false');
assertTrue('quit は終了を伝える', runCommand(INITIAL_PRODUCTS, 'quit').quit);
assertText('quit のメッセージ', runCommand(INITIAL_PRODUCTS, 'quit').output, '終了します。');
assertText('空行は何も出力しない', runCommand(INITIAL_PRODUCTS, '   ').output, '');
assertText(
  'search のキーワードが無いとき',
  runCommand(INITIAL_PRODUCTS, 'search').output,
  'search の後ろに検索キーワードを指定してください。（例: search マグ）'
);
assertNumber('help は7行', HELP_LINES.length, 7);
assertText('help の1行目', HELP_LINES[0] ?? '', '=== コマンド一覧 ===');

// --- 課題7: 通し動作 -----------------------------------------------
const scenario = runCommands(INITIAL_PRODUCTS, DEMO_COMMANDS);
assertNumber('logs の件数（quit までの10件）', scenario.logs.length, 10);
assertText('最後のログ', scenario.logs.at(-1) ?? '', '終了します。');
assertText(
  '追加成功のログ',
  scenario.logs[3] ?? '',
  '「入浴剤」を追加しました。（単価 650円 / 在庫 10点）'
);
assertText(
  '重複追加のログ',
  scenario.logs[4] ?? '',
  '「ラベンダーの石けん」はすでに登録されています。'
);
assertText('名前なし追加のログ', scenario.logs[5] ?? '', '商品名を入力してください。');
assertText(
  '引数不足のログ',
  scenario.logs[6] ?? '',
  'add の引数は「名前,単価,在庫数」の3つをカンマ区切りで指定してください。'
);
assertText(
  '未知のコマンドのログ',
  scenario.logs[8] ?? '',
  '不明なコマンドです：stock（help でコマンド一覧を表示します）'
);
assertNumber('通し実行後の件数', scenario.products.length, 6);
assertNumber('通し実行後の在庫金額合計', calcTotalStockValue(scenario.products), 60670);
assertNumber('通し実行後も元の配列は5件', INITIAL_PRODUCTS.length, 5);
assertNumber('通し実行後も元の在庫金額合計は変わらない', calcTotalStockValue(INITIAL_PRODUCTS), 54170);

// ===== 14. 結果の報告 ==============================================

if (failureCount > 0) {
  console.error(`mid01: ${failureCount} 件の検証に失敗しました`);
  process.exit(1);
}
console.log('mid01: ok');
