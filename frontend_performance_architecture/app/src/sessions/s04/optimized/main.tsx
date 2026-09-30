import { mountCatalog } from '../mountCatalog';
import { runThirdPartyTag } from '../third-party-tag';
import { reportWebVitals } from '../../../vitals';

mountCatalog();
reportWebVitals();

// 最初の描画に要らない外部タグは、load（画像やスクリプトの読み込み完了）の後に回す。
// module スクリプトは defer と同じく「解析の完了後・load の前」に実行されるため、
// ここで直接呼ぶと、まだ描画されていないヒーロー画像の描画を止めてしまうことがある。
window.addEventListener('load', runThirdPartyTag, { once: true });
