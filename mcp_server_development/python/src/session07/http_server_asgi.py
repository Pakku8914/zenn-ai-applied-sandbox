import uvicorn

from create_server import create_docsearch_server

mcp = create_docsearch_server(DOCS_ROOT)
# メソッド名は上の確認コマンドで調べたものに置き換える
app = mcp.streamable_http_app()
uvicorn.run(app, host=HOST, port=PORT, log_level="info")
