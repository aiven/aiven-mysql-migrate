from aiven_mysql_migrate.migration import MySQLMigrateMethod, MySQLMigration
from aiven_mysql_migrate.utils import MySQLConnectionInfo
from pytest import fixture, mark

import logging
import random
import string
import time

MYSQL_WAIT_RETRIES = 30
MYSQL_WAIT_SLEEP = 2
LOGGER = logging.getLogger(__name__)


class TimeoutException(Exception):
    pass


@fixture(name="db_name")
def random_db_name():
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def my_wait(host, ssl=True, retries=MYSQL_WAIT_RETRIES) -> MySQLConnectionInfo:
    uri = f"mysql://root:test@{host}/"
    if not ssl:
        uri += "?ssl-mode=DISABLE"
    conn = MySQLConnectionInfo.from_uri(uri)
    for _ in range(retries):
        try:
            with conn.cur() as cur:
                cur.execute("SELECT VERSION()")
                return conn
        except Exception as ex:  # pylint: disable=broad-except
            LOGGER.warning("%s is not yet ready: %s", host, ex)
            time.sleep(MYSQL_WAIT_SLEEP)
    raise TimeoutException(f"Timeout while waiting for {host}")


@mark.parametrize(
    "src,dst", [
        (my_wait("mysql57-src-1"), my_wait("mysql80-dst-1")),
        (my_wait("mysql80-src-2"), my_wait("mysql80-dst-2")),
    ]
)
def test_migration_replication(src, dst, db_name):
    with src.cur() as cur:
        cur.execute(f"CREATE DATABASE {db_name}")
        cur.execute(f"USE {db_name}")
        cur.execute("CREATE TABLE test (ID TEXT)")
        cur.execute("INSERT INTO test (ID) VALUES (%s)", ["test_data"])
        cur.execute("COMMIT")

    migration = MySQLMigration(
        source_uri=src.to_uri(),
        target_uri=dst.to_uri(),
        target_master_uri=dst.to_uri(),
        privilege_check_user="root@%",
    )
    method = migration.run_checks()
    assert method == MySQLMigrateMethod.replication
    migration.start(migration_method=method, seconds_behind_master=0)

    with dst.cur() as cur:
        cur.execute(f"SELECT ID FROM {db_name}.test")
        res = cur.fetchall()
        assert len(res) == 1 and res[0]["ID"] == "test_data"

    with src.cur() as cur:
        cur.execute(f"INSERT INTO {db_name}.test (ID) VALUES (%s)", ["repl_data"])
        cur.execute("COMMIT")

    for _ in range(5):
        with dst.cur() as cur:
            cur.execute(f"SELECT ID FROM {db_name}.test")
            res = cur.fetchall()
            if len(res) == 2 and sorted(["test_data", "repl_data"]) == sorted([item["ID"] for item in res]):
                return
        time.sleep(1)

    raise TimeoutException()


@mark.parametrize("src,dst", [
    (my_wait("mysql80-src-3"), my_wait("mysql80-dst-3")),
])
def test_migration_fallback(src, dst, db_name):
    with src.cur() as cur:
        cur.execute(f"CREATE DATABASE {db_name}")
        cur.execute(f"USE {db_name}")
        cur.execute("CREATE TABLE test (ID TEXT)")
        cur.execute("INSERT INTO test (ID) VALUES (%s)", ["test_data"])
        cur.execute("CREATE PROCEDURE test_proc (OUT body TEXT) BEGIN SELECT 'test_body'; END")
        cur.execute("COMMIT")

    migration = MySQLMigration(
        source_uri=src.to_uri(),
        target_uri=dst.to_uri(),
        target_master_uri=dst.to_uri(),
    )
    method = migration.run_checks()
    assert method == MySQLMigrateMethod.dump
    migration.start(migration_method=method, seconds_behind_master=0)

    with dst.cur() as cur:
        cur.execute(f"SELECT ID FROM {db_name}.test")
        res = cur.fetchall()
        assert len(res) == 1 and res[0]["ID"] == "test_data"

        cur.execute(f"call {db_name}.test_proc(@body)")
        res = cur.fetchall()
        assert len(res) == 1 and res[0]["test_body"] == "test_body"
