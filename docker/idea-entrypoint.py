#!/usr/bin/env python
"""
Entrypoint of the IDEA production image (koenswings/kolibri-studio, see Dockerfile).

Like docker/entrypoint.py (upstream, development only) it waits for Postgres and MinIO and then
runs the CMD, but it does not run `manage.py setup --settings=contentcuration.dev_settings`:
that needs requirements-dev (dev_settings), and it adds four sample users and four sample
channels on EVERY start. Instead, on every start (all steps are idempotent):
  - create the storage bucket with its public-read policy if it does not exist;
  - createcachetable, migrate, loadconstants (upstream "make migrate" + setup's first steps);
  - set the Django Site domain (loadconstants resets it to studio.learningequality.org):
    STUDIO_SITE_DOMAIN, else <IDEA_HOSTNAME>.local:<IDEA_APP_PORT> (the Engine writes IDEA_HOSTNAME
    into every instance .env), else localhost:<IDEA_APP_PORT>;
  - create the admin account only if there is no admin yet: STUDIO_ADMIN_EMAIL /
    STUDIO_ADMIN_PASSWORD (defaults admin@idea.local / admin911!). The credentials are never logged.

A second container of the same image (the celery worker) passes --no-prepare as the first argument
(or sets IDEA_SKIP_PREPARE=1): it only waits for Postgres and MinIO and then runs its command;
studio-app does the preparation. Compose: entrypoint ["python", "docker/idea-entrypoint.py", "--no-prepare"].
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
    # Log the subcommand only (the shell -c snippet is long; it holds no credentials).
    logging.info("manage.py %s", args[0])
    subprocess.check_call(MANAGE + list(args))


PREPARE = """
import os
from django.conf import settings
from django.contrib.sites.models import Site
from contentcuration.models import User
from contentcuration.utils.minio_utils import ensure_storage_bucket_public

ensure_storage_bucket_public(will_sleep=False)

domain = os.environ["IDEA_RESOLVED_SITE_DOMAIN"]
Site.objects.update_or_create(id=settings.SITE_ID, defaults={"domain": domain, "name": "Kolibri Studio"})
print("Site {} domain: {}".format(settings.SITE_ID, domain))

if not User.objects.filter(is_admin=True).exists():
    # Not db_tools.create_user: it prints the password.
    email = (os.getenv("STUDIO_ADMIN_EMAIL") or "admin@idea.local").strip().lower()
    user, _new = User.objects.get_or_create(email=email)
    user.set_password(os.getenv("STUDIO_ADMIN_PASSWORD") or "admin911!")
    user.first_name, user.last_name = "Admin", "User"
    user.is_staff = user.is_admin = user.is_active = True
    user.save()
    print("Admin account created (credentials from STUDIO_ADMIN_EMAIL / STUDIO_ADMIN_PASSWORD or the defaults)")
"""


def site_domain(env):
    """STUDIO_SITE_DOMAIN, else <IDEA_HOSTNAME>.local[:<IDEA_APP_PORT>], else localhost[:<IDEA_APP_PORT>]."""
    explicit = (env.get("STUDIO_SITE_DOMAIN") or "").strip()
    if explicit:
        return explicit
    host = (env.get("IDEA_HOSTNAME") or "").strip()
    port = (env.get("IDEA_APP_PORT") or "").strip()
    return (host + ".local" if host else "localhost") + (":" + port if port else "")


def prepare():
    os.environ["IDEA_RESOLVED_SITE_DOMAIN"] = site_domain(os.environ)
    manage("createcachetable")
    manage("migrate")
    manage("loadconstants")
    manage("shell", "-c", PREPARE)


if __name__ == "__main__":
    wait_for_postgres()
    wait_for_minio()
    cmd = sys.argv[1:]
    skip = os.getenv("IDEA_SKIP_PREPARE") == "1"
    if cmd[:1] == ["--no-prepare"]:
        cmd, skip = cmd[1:], True
    if not skip:
        prepare()
    if not cmd:
        logging.error("No command given")
        sys.exit(2)
    os.execvp(cmd[0], cmd)
