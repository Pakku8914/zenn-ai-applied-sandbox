# workflow-requests-mcp

社内申請ワークフロー（検索・詳細・起票・提出・決裁・コメント）を扱う MCP サーバーです。
Streamable HTTP で待ち受け、OAuth 2.1 のアクセストークンで保護します。

## 使い方

    AUDIT_PEPPER=<16文字以上のランダム文字列> npx workflow-requests-mcp \
      --port 3939 --issuer https://id.example.com

## スコープ

| スコープ | 使えるツール |
| --- | --- |
| requests:read | search_requests / get_request / request://{id} / draft_request |
| requests:write | save_request / submit_request / comment_on_request |
| requests:approve | decide_request |

requests:read は接続に必須です。決裁は二段階（ドライラン → 確定）です。

## ライセンス

MIT
