// 練習問題2 (C)：名前空間オブジェクトごと別の関数に渡すと、全関数が残る
import * as fmt from './format-utils';
import { register } from './registry';

register(fmt);
