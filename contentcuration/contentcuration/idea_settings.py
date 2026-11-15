# flake8: noqa
"""
IDEA settings: Kolibri Studio as an offline App on an IDEA Pi (koenswings/app-kolibri-studio).

Production-style: DEBUG off, a webpack production build served by gunicorn + whitenoise, and
storage on the App's own MinIO (S3). Not dev_settings (DEBUG, dev_urls, the webpack devserver on
:4000, drf_yasg/automation from requirements-dev) and not production_settings (Google Cloud
Storage, Postmark, Secret Manager, Prometheus).
"""
import os

from .settings import *  # noqa

DEBUG = False

# The App is reached by IP or by name on the school LAN; the host is not known in advance.
ALLOWED_HOSTS = ["*"]

# contentcuration.urls plus /content/ served from MinIO (see idea_urls.py).
ROOT_URLCONF = "contentcuration.idea_urls"

# /static/ from STATIC_ROOT (filled by collectstatic in the image build). Upstream production uses
# nginx for this; whitenoise keeps the App to one web container and one port.
MIDDLEWARE = ("whitenoise.middleware.WhiteNoiseMiddleware",) + MIDDLEWARE

# The bucket is created once by docker/idea-entrypoint.py. With True, apps.py ready() would contact
# MinIO in every process, including collectstatic during the image build.
AWS_AUTO_CREATE_BUCKET = False

# Presigned upload URLs are rewritten to this same-origin prefix and proxied to MinIO by Studio itself
# (utils/idea_upload.py, idea_urls.py), so browsers never need to reach http://minio:9000.
IDEA_SAME_ORIGIN_UPLOAD_PREFIX = "/content-upload/"

# One Site; docker/idea-entrypoint.py sets its domain from STUDIO_SITE_DOMAIN or the Engine's
# IDEA_HOSTNAME (<name>.local) on every start, never studio.learningequality.org.
SITE_ID = 1

# No outgoing mail on an offline Pi: activation and password mails go to the container log.
EMAIL_BACKEND = os.getenv("STUDIO_EMAIL_BACKEND") or "django.core.mail.backends.console.EmailBackend"

# Local offline administrator login alias (the underlying User remains e-mail-based).
IDEA_ADMIN_LOGIN_ALIAS = True
