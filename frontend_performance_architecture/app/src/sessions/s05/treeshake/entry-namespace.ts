// Bad：名前空間ごと import し、実行時に決まるキーで関数を選ぶ。
// どの関数が使われるかビルド時に分からないため、全関数がバンドルに残る
import * as fmt from './format-utils';

const kind = (new URLSearchParams(location.search).get('kind') ?? 'formatPrice') as keyof typeof fmt;
document.title = fmt[kind](1200);
