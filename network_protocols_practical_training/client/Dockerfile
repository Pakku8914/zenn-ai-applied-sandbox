# 観察ラボのクライアント（学習者シェル）
# tcpdump / dig / curl / openssl など、ネットワーク観察ツール一式をそろえる。
# ベースは Debian 12 (bookworm) に固定（latest は使わない）。
FROM debian:12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        dnsutils \
        iputils-ping \
        iproute2 \
        traceroute \
        mtr-tiny \
        tcpdump \
        netcat-openbsd \
        curl \
        wget \
        openssl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# client サービスでは compose 側で `sleep infinity` を指定して常駐させる。
# certgen サービスでは compose 側で entrypoint を上書きして証明書を生成する。
CMD ["sleep", "infinity"]
