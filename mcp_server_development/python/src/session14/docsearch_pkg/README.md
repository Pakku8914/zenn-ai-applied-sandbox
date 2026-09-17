# docsearch-mcp（Python 版）

社内の Markdown 文書を全文検索する、読み取り専用の MCP サーバーです。stdio で動きます。

## 使い方

```json
{
  "mcpServers": {
    "docsearch": {
      "command": "uvx",
      "args": ["docsearch-mcp", "--docs-root", "/abs/path/to/docs"]
    }
  }
}
```

## 設定項目

| 項目 | 指定方法 | 必須 |
| :--- | :--- | :--- |
| 検索対象ディレクトリ | `--docs-root <DIR>` または環境変数 `DOCSEARCH_ROOT` | 必須 |

公開するツールは `search_documents` の 1 本だけです（TypeScript 版はリソースとプロンプトも公開します）。

## 要求環境

- Python 3.11 以上

## ライセンス

MIT
