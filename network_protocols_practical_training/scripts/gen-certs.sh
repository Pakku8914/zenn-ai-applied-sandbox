#!/bin/sh
# ラボ用の自己署名CA（ルート証明書）とサーバ証明書を生成する。
# web サーバが HTTPS を提供するために起動前に一度だけ実行される（certgen サービス）。
# 既に証明書があれば何もしない（冪等）。
set -e

CERT_DIR=/certs
CN=web.lab.example

if [ -f "$CERT_DIR/$CN.crt" ]; then
  echo "[certgen] 証明書は既に存在します。生成をスキップします。"
  exit 0
fi

mkdir -p "$CERT_DIR"
echo "[certgen] ラボ用の自己署名CAとサーバ証明書を生成します..."

# 1) ラボCA（ルート証明書）を作る。これが「信頼の起点」になる。
openssl genrsa -out "$CERT_DIR/ca.key" 2048
openssl req -x509 -new -nodes -key "$CERT_DIR/ca.key" -sha256 -days 3650 \
  -subj "/O=NetLab/CN=NetLab Local CA" \
  -out "$CERT_DIR/ca.crt"

# 2) サーバの秘密鍵と署名要求(CSR)を作る。
openssl genrsa -out "$CERT_DIR/$CN.key" 2048
openssl req -new -key "$CERT_DIR/$CN.key" \
  -subj "/O=NetLab/CN=$CN" \
  -out "$CERT_DIR/$CN.csr"

# 3) ラボCAでサーバ証明書に署名する。SAN（サブジェクト代替名）にドメインを入れる。
cat > "$CERT_DIR/$CN.ext" <<EOF
subjectAltName = DNS:$CN
EOF
openssl x509 -req -in "$CERT_DIR/$CN.csr" \
  -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial \
  -days 825 -sha256 -extfile "$CERT_DIR/$CN.ext" \
  -out "$CERT_DIR/$CN.crt"

echo "[certgen] 完了しました。生成物:"
ls -1 "$CERT_DIR"
