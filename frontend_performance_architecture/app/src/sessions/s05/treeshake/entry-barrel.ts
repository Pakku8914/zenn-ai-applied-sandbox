// formatPrice だけを使う。analytics.ts には何も触れていないが、
// 最上位の副作用があるため、sideEffects の宣言がないとバンドルに残る
import { formatPrice } from './lib';

document.title = formatPrice(1200);
