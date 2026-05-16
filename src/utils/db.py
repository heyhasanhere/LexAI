import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from typing import Generator

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool(dsn: str, minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn)


@contextmanager
def get_conn(dsn: str) -> Generator:
    if _pool is not None:
        conn = _pool.getconn()
        conn.autocommit = True
        try:
            yield conn
        finally:
            _pool.putconn(conn)
    else:
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        try:
            yield conn
        finally:
            conn.close()
