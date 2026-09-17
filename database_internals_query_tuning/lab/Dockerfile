FROM python:3.14.7-slim-trixie

# psql（PostgreSQL 18 クライアント）と mysql クライアントを入れる。
# trixie の postgresql-client は 17 系なので、PGDG リポジトリから 18 を明示的に取得する。
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg lsb-release \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-18 default-mysql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
