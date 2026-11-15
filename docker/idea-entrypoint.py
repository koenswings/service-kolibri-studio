#!/usr/bin/env python
"""
Entrypoint of the IDEA production image (koenswings/kolibri-studio, see Dockerfile).

Like docker/entrypoint.py (upstream, development only) it waits for Postgres and MinIO and then
runs the CMD, but it does not run `manage.py setup --settings=contentcuration.dev_settings`:
that needs requirements-dev (dev_settings), and it adds four sample users and four sample
channels on EVERY start. Instead, on every start (all steps are idempotent):
  - create the storage bucket with its public-read policy if it does not exist;
  - createcachetable, migrate, loadconstants (upstream "make migrate" + setup's first steps);
  - create the admin account only if there is no admin yet
    (STUDIO_ADMIN_EMAIL / STUDIO_ADMIN_PASSWORD, defaults as upstream setup: a@a.com / a).
"""
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO)

CONNECT_TRIES = int(os.getenv("STUDIO_CONNECT_TRIES") or 60)
MANAGE = ["python", "contentcuration/manage.py"]


def wait_for_postgres():
    import psycopg2

    for attempt in range(CONNECT_TRIES):
        try:
            psycopg2.connect(
                dbname=os.getenv("DATA_DB_NAME") or "kolibri-studio",
                user=os.getenv("DATA_DB_USER") or "learningequality",
                password=os.getenv("DATA_DB_PASS") or "kolibri",
                host=os.getenv("DATA_DB_HOST") or "localhost",
            ).close()
            logging.info("Postgres is ready")
            return
        except psycopg2.OperationalError:
            logging.info("Postgres not ready (%d/%d)", attempt + 1, CONNECT_TRIES)
            time.sleep(2)
    logging.error("Postgres did not become ready")
    sys.exit(1)


def wait_for_minio():
    import requests

    url = os.getenv("AWS_S3_ENDPOINT_URL") or "http://localhost:9000"
    for attempt in range(CONNECT_TRIES):
        try:
            # Anonymous request: MinIO answers 403 once it serves S3.
            if requests.get(url, timeout=5).status_code == 403:
                logging.info("MinIO is ready")
                return
        except requests.exceptions.RequestException:
            pass
        logging.info("MinIO not ready (%d/%d)", attempt + 1, CONNECT_TRIES)
        time.sleep(2)
    logging.error("MinIO did not become ready")
    sys.exit(1)


def manage(*args):
    logging.info("manage.py %s", " ".join(args))
    subprocess.check_call(MANAGE + list(args))


PREPARE = """
import os
from contentcuration.models import User
from contentcuration.utils.db_tools import create_user
from contentcuration.utils.minio_utils import ensure_storage_bucket_public

ensure_storage_bucket_public(will_sleep=False)
if not User.objects.filter(is_admin=True).exists():
    create_user(
        os.getenv("STUDIO_ADMIN_EMAIL") or "a@a.com",
        os.getenv("STUDIO_ADMIN_PASSWORD") or "a",
        "Admin", "User", admin=True,
    )
"""


def prepare():
    manage("createcachetable")
    manage("migrate")
    manage("loadconstants")
    manage("shell", "-c", PREPARE)


if __name__ == "__main__":
    wait_for_postgres()
    wait_for_minio()
    prepare()
    cmd = sys.argv[1:]
    if not cmd:
        logging.error("No command given")
        sys.exit(2)
    os.execvp(cmd[0], cmd)
