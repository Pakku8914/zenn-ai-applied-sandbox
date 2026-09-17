// エントリポイント。ここだけが console.log を持ち、誰からも import されない。
import { buildReport } from './report';

console.log(buildReport('silver'));
