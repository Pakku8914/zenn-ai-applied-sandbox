// ミニ雑貨ショップの CLI 在庫管理ツール（中間プロジェクト1）
// 実行: docker compose exec ts npx tsx src/mid01/inventory.ts
//
// import/export は Phase 4 で学ぶため、1ファイルをセクションコメントで区切って書く。
// 各セクションが、後でそのままファイルに切り出せる単位になっている。

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

/** 1商品の在庫金額（単価 × 在庫数）。使うプロパティだけを引数の型に書く */
const calcStockValue = (product: { price: number; stock: number }): number =>
  product.price * product.stock;

// ===== 4. 金額と数量の整形 =========================================

/** 3桁ごとにカンマを入れる（11520 → "11,520"） */
const formatNumberWithComma = (value: number): string => {
  let rest = `${value}`;
  let grouped = '';
  while (rest.length > 3) {
    // 末尾3文字を切り出して前に足し、残りをさらに処理する
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
  // ラベルが無いときに行末へ余分な空白を残さない
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
    // includes('') はすべて true になるため、空のキーワードは0件として扱う
    return [];
  }
  return products.filter((product) => product.name.toLowerCase().includes(normalized));
};

/** 同じ名前の商品が登録済みかどうか（追加時の重複チェックで使う） */
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
  // Number.isNaN で「数値にできなかった値」を先に弾き、次に範囲と整数を見る
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
    // 失敗時は受け取った配列をそのまま返す（新しい商品は作らない）
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
  // toSorted は元の配列を並べ替えず、並べ替えた新しい配列を返す
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
  // インデックスアクセスの結果は undefined の可能性があるため ?? で既定値を用意する
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
      // 空行は何も出力せず次へ進む
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
      // case の中で const を宣言するときは波かっこで囲む
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

/**
 * コマンドの配列を順に処理する。ここも画面出力はしない。
 * 画面出力なしで同じ処理を回せる入口として、検証スクリプトから使う。
 */
const runCommands = (
  initialProducts: { name: string; price: number; stock: number }[],
  commands: string[]
): { products: { name: string; price: number; stock: number }[]; logs: string[] } => {
  let products = initialProducts;
  const logs: string[] = [];
  for (const line of commands) {
    const result = runCommand(products, line);
    // 新しい在庫で置き換える（元の配列は変えない）
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

// この関数は検証スクリプト（verify.ts）から呼ぶための入口。
// inventory.ts では下の画面出力セクションが同じループを出力付きで回している。

// ===== 11. 画面出力（このセクションだけが副作用を持つ） ============

/** 動作確認用のコマンド列（キーボード入力の代わり） */
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

let currentProducts = INITIAL_PRODUCTS;
for (const line of DEMO_COMMANDS) {
  console.log(`> ${line}`);
  const result = runCommand(currentProducts, line);
  currentProducts = result.products;
  if (result.output !== '') {
    console.log(result.output);
  }
  console.log('');
  if (result.quit) {
    break;
  }
}
