// この章では学習のために、型注釈をすべて明示して書く。
const productName: string = 'マグカップ';
const price: number = 1200;
const stock: number = 12;
const isOnSale: boolean = true;

// 「意図して無い」を表す null
const discontinuedNote: null = null;
// 「まだ何も入っていない」を表す undefined
const shippingDate: undefined = undefined;

console.log(typeof productName); // string
console.log(typeof price); // number
console.log(typeof isOnSale); // boolean
console.log(typeof shippingDate); // undefined
console.log(typeof discontinuedNote); // object （JavaScript の有名な仕様）

console.log('null を表示:', discontinuedNote);
console.log('undefined を表示:', shippingDate);
console.log('在庫:', stock);
