import MySQLdb

from config import MYSQL_CHARSET, MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER


def get_db():
    return MySQLdb.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        passwd=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset=MYSQL_CHARSET,
    )
