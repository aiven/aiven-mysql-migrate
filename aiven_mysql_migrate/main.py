# Copyright (c) 2020 Aiven, Helsinki, Finland. https://aiven.io/
from aiven_mysql_migrate import config
from aiven_mysql_migrate.migration import MySQLMigrateMethod, MySQLMigration

import logging

LOGGER = logging.getLogger(__name__)


def setup_logging(*, debug=False):
    log_format = "%(asctime)s\t%(name)s\t%(levelname)s\t%(message)s"
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level, format=log_format)


def main(args=None, *, app="mysql_migrate"):
    """Migrate MySQL database from source to target, take configuration from CONFIG"""
    import argparse
    parser = argparse.ArgumentParser(description="MySQL migration tool.", prog=app)
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "-f", "--filter-dbs", help="Comma separated list of databases to filter out during migration", required=False
    )
    parser.add_argument("--validate-only", action="store_true", help="Run migration pre-checks only")
    parser.add_argument(
        "--seconds-behind-master",
        type=int,
        default=-1,
        help="Max replication lag in seconds to wait for, by default no wait"
    )
    parser.add_argument(
        "--stop-replication", action="store_true", help="Stop replication, by default replication is left running"
    )
    parser.add_argument(
        "--privilege-check-user",
        type=str,
        required=False,
        help="User to be used when replicating for privileges check "
        "(e.g. 'checker@%%', must have REPLICATION_APPLIER grant)"
    )
    args = parser.parse_args(args)
    setup_logging(debug=args.debug)

    assert config.SOURCE_SERVICE_URI, "SOURCE_SERVICE_URI is not specified"
    assert config.TARGET_SERVICE_URI, "TARGET_SERVICE_URI is not specified"

    migration = MySQLMigration(
        source_uri=config.SOURCE_SERVICE_URI,
        target_uri=config.TARGET_SERVICE_URI,
        target_master_uri=config.TARGET_MASTER_SERVICE_URI,
        filter_dbs=args.filter_dbs,
        privilege_check_user=args.privilege_check_user,
    )

    LOGGER.info("MySQL migration from %s to %s", migration.source.hostname, migration.target.hostname)

    LOGGER.info("Starting pre-checks")
    migration_method = migration.run_checks()

    if migration_method == MySQLMigrateMethod.replication:
        LOGGER.info("All pre-checks passed successfully.")
    else:
        LOGGER.info("Not all pre-checks passed successfully. Replication method is not available.")

    if args.validate_only:
        return

    LOGGER.info("Starting migration using method: %s", migration_method)
    migration.start(
        migration_method=migration_method,
        seconds_behind_master=args.seconds_behind_master,
        stop_replication=args.stop_replication,
    )

    LOGGER.info("Migration finished.")
    if migration_method == MySQLMigrateMethod.replication and not args.stop_replication:
        LOGGER.info("IMPORTANT: Replication is still running, make sure to stop it after switching to the target DB")


if __name__ == "__main__":
    import sys
    sys.exit(main())
