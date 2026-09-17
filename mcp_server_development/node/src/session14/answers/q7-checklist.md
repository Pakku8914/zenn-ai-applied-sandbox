# 配布前チェックリスト（docsearch-mcp）

## A. npm / PyPI 共通

1. [ ] 版番号を上げたか（`package.json` / `__init__.py`）→ `git diff` で確認
2. [ ] 版番号の分類（major/minor/patch）をチームで合意したか → CHANGELOG のレビュー
3. [ ] `serverInfo.version` がパッケージの版と一致するか → `probe-stdio.ts` の出力
4. [ ] CHANGELOG に「何が壊れるか・どう直すか」を書いたか → 破壊的変更の節の有無
5. [ ] README の設定項目表・`--help` の文面が最新か → 実際に `--help` を実行して読み比べ
6. [ ] ライセンス表記とライセンスファイルが一致するか → 両方を目視
7. [ ] テストが通るか → `npm test` / `python -m pytest -q`
8. [ ] スキーマスナップショットテストが通るか（落ちたら版番号を再確認）→ CI の結果

## B. npm 固有

9. [ ] ビルド成果物が最新か → `dist/` を消してから再ビルド
10. [ ] `npm pack --dry-run` の一覧に `bin` の対象が入っているか → `check-package.ts`
11. [ ] `bin` に実行権限が付いているか → `ls -l dist/cli.js`
12. [ ] シバンが `#!/usr/bin/env node` か → `head -n 1 dist/cli.js`
13. [ ] `dependencies` に実行時依存だけが入っているか → 一覧を目視
14. [ ] `engines` の下限で実際に動くか → その版のコンテナで起動
15. [ ] 社内限定なら `private: true` が付いているか → `check-package.ts` の WARN

## C. PyPI 固有

16. [ ] `[project.scripts]` のエントリーポイントが import できるか → `pack_sdist.py`
17. [ ] パッケージ内 import が相対 import になっているか → `grep -rn "^import docs_domain"` が 0 件
18. [ ] `requires-python` の下限で動くか → その版のコンテナで起動
19. [ ] sdist と wheel の両方にモジュールが入っているか → `include` / `packages` の設定を確認

## D. Docker 固有

20. [ ] 起動例に `-i` が入っているか（`-t` が入っていないか）→ README の目視
21. [ ] ボリュームの例が `:ro` になっているか → README の目視
22. [ ] root で動かしていないか → Dockerfile の `USER`
23. [ ] 実行段に devDependencies が入っていないか → `npm ci --omit=dev` の有無

## E. セキュリティ

24. [ ] 配布物に秘密情報が無いか → `check-package.ts` / `pack_sdist.py` が exit 0
25. [ ] 秘密情報を受け取る設定項目が `env` 経由か（`args` でないか）→ `--help` と README
26. [ ] エラーメッセージに内部パスや入力値が混ざっていないか → 異常系の実行結果を目視
27. [ ] 書き込み系のツールが増えていないか → `tools/list` の注釈を確認
28. [ ] 依存に既知の脆弱性が無いか → 監査コマンドの結果

## F. バージョニング・告知

29. [ ] 破壊的変更がある場合、非推奨期間を設けたか → 旧名・旧キーが残っているか
30. [ ] 非推奨の告知を `description`（モデルが読む場所）に書いたか → `tools/list` の出力
31. [ ] 利用者が版を固定する方法を README に書いたか → 目視
