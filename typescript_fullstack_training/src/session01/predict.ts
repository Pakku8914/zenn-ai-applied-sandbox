// 練習問題5（前半）の解答。出力を予測してから実行するための材料。

const categoryName: string = 'キッチン';
const shippingFee: number = 500;
const isFreeShipping: boolean = false;
const discontinuedNote: null = null;
const shippingDate: undefined = undefined;

console.log(typeof categoryName); // string
console.log(typeof shippingFee); // number
console.log(typeof isFreeShipping); // boolean
console.log(typeof discontinuedNote); // object （ここが外れやすい）
console.log(typeof shippingDate); // undefined
console.log('値の表示:', discontinuedNote, shippingDate); // 値の表示: null undefined
