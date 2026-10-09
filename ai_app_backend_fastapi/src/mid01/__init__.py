"""中間プロジェクト1：献立相談チャット API（会話の保存・ツール呼び出し・ストリーミングを1本にする）。

S04〜S08 の部品をコピーして組み立てる（他のセッションは import しない）。
- providers.py … session06（review01 版の retry_after 付き）
- errors.py / sse.py … session06・session08
- tools.py / loop.py … session08
- models.py / repo.py / deps.py / tokens.py / history.py / migrations … session07 を手直し
- turn.py / relay.py … このプロジェクトで書く（保存するものの決め方と、先読み・中継・保存の順序）
"""
