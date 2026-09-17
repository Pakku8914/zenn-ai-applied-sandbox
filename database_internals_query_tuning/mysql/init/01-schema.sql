-- InnoDB バッファプールの中身（information_schema.innodb_buffer_page）を読むには
-- PROCESS 権限が必要。学習用サンドボックスなので lab ユーザーに付与する。
GRANT PROCESS ON *.* TO 'lab'@'%';
FLUSH PRIVILEGES;

-- 比較用の MySQL 側スキーマ（PostgreSQL と同じ構造にしてある）。
-- InnoDB はクラスタ化インデックスを採るため、同じスキーマでも物理配置が変わる。その差を S 内で比較する。
CREATE TABLE customers (
    id          INT           PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    email       VARCHAR(255)  NOT NULL,
    region      VARCHAR(20)   NOT NULL,
    created_at  DATETIME      NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE products (
    id        INT           PRIMARY KEY,
    name      VARCHAR(100)  NOT NULL,
    category  VARCHAR(20)   NOT NULL,
    price     INT           NOT NULL,
    stock     INT           NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
    id           BIGINT       PRIMARY KEY,
    customer_id  INT          NOT NULL,
    ordered_at   DATETIME     NOT NULL,
    status       VARCHAR(10)  NOT NULL,
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_items (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id    BIGINT  NOT NULL,
    product_id  INT     NOT NULL,
    quantity    INT     NOT NULL,
    unit_price  INT     NOT NULL,
    CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders(id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
