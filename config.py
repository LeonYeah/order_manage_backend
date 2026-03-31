import os


MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DB = os.getenv("MYSQL_DB", "product_order_system")
MYSQL_CHARSET = os.getenv("MYSQL_CHARSET", "utf8mb4")
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key_here")
