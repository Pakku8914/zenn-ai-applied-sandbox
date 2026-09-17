// セッション20「WebとHTTPの基礎・Node.jsサーバー」
//
// 検証やテストからサーバーを起動・停止するための道具。
// ポート番号を固定すると「別の何かが使っている」で落ちるため、
// OS に空きポートを選ばせてから、その番号を受け取る形にしている。

import type { Server } from 'node:http';

/** 空いているポートで待ち受けを始め、実際に割り当てられた番号を返す */
export function listenOnRandomPort(server: Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);

    // 0 を指定すると OS が空きポートを選ぶ。127.0.0.1 なので外からは見えない
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();

      if (address === null || typeof address === 'string') {
        reject(new Error('ポート番号を取得できませんでした'));
        return;
      }
      // 待ち受けだけでプロセスを生かし続けないようにする（検証が終わったら終了させたい）
      server.unref();
      resolve(address.port);
    });
  });
}

/** 待ち受けを終える。呼び忘れるとプロセスが終わらない */
export function closeServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((error) => {
      if (error === undefined) {
        resolve();
        return;
      }
      reject(error);
    });

    // fetch は接続を使い回すので、待ち受けを止めても接続が残る。
    // 残った接続を切らないと close の完了が数秒遅れる。
    server.closeAllConnections();
  });
}
