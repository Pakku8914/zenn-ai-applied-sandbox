# docsearch-mcp

社内の Markdown 文書を全文検索する、**読み取り専用**の MCP サーバーです。stdio で動きます。

## できること

| 種別 | 名前 | 概要 |
| :--- | :--- | :--- |
| ツール | `search_documents` | Markdown 群を全文検索し、一致した文書への参照（`docs://` URI）を返します |
| リソース | `docs://{+path}` | 文書 1 件の本文を `text/markdown` で返します |
| プロンプト | `summarize_search` | 検索結果から要約の下書きを組み立てます |

書き込み系のツールはありません。指定したディレクトリの外にあるファイルは読みません。

## 使い方

```json
{
  "mcpServers": {
    "docsearch": {
      "command": "npx",
      "args": ["-y", "docsearch-mcp", "--docs-root", "/abs/path/to/docs"]
    }
  }
}
```

## 設定項目

| 項目 | 指定方法 | 必須 | 説明 |
| :--- | :--- | :--- | :--- |
| 検索対象ディレクトリ | `--docs-root <dir>` または環境変数 `DOCSEARCH_ROOT` | 必須 | Markdown が置かれたディレクトリ。絶対パスを推奨 |

## 要求環境

- Node.js 20 以上

## ライセンス

MIT
