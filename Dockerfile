# Kolibri Studio production image for IDEA (app-kolibri-studio, release blockers in
# koenswings/app-kolibri-studio#2).
#
# Follows upstream Studio v2024.12.03 docker/Dockerfile.prod (yarn run build in the image), but:
# - serves through gunicorn + whitenoise on :8080 directly (upstream puts nginx in front of gunicorn
#   on :8081); no webpack devserver, so no :4000 port;
# - uses contentcuration.idea_settings (offline, MinIO/S3 storage), not dev_settings or
#   production_settings (GCS + Postmark + Secret Manager);
# - collectstatic and compilemessages run at build time (upstream "make altprodserver" runs them on
#   every start);
# - docker/idea-entrypoint.py prepares the database and the bucket on start (no sample data).
#
# Build on an ARM64 Pi (see app-kolibri-studio README "Building the images"):
#   docker buildx build --builder <throwaway> --platform linux/arm64 --load \
#     -t koenswings/kolibri-studio:<tag> .
FROM python:3.10-slim-bookworm

# Set the timezone (as upstream)
RUN ln -fs /usr/share/zoneinfo/America/Los_Angeles /etc/localtime

ENV DEBIAN_FRONTEND=noninteractive
# Default Python file.open file encoding to UTF-8 instead of ASCII, workaround for le-utils setup.py issue
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# System packages (upstream Dockerfile.prod list, plus gettext for compilemessages)
RUN apt-get update && \
    apt-get -y install --no-install-recommends \
        python3-dev gcc libpq-dev libssl-dev libffi-dev make git curl gettext libjpeg-dev ffmpeg \
        ca-certificates gnupg

# Pin, download and install node 16.x (as upstream; package.json volta pins node 16.20.2)
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_16.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && printf 'Package: nodejs\nPin: origin deb.nodesource.com\nPin-Priority: 1001\n' > /etc/apt/preferences.d/preferences \
    && apt-get update \
    && apt-get install -y nodejs \
    && npm install --location=global yarn && npm cache clean --force

WORKDIR /src

# Node packages (cached layer: only package.json + yarn.lock)
COPY package.json yarn.lock /src/
RUN yarn install --frozen-lockfile --network-timeout 600000 && yarn cache clean

# Python packages: production requirements only (gunicorn is in requirements.txt), plus the two
# runtime packages that upstream only lists in requirements-dev.txt, at the same pins:
# - whitenoise: serves /static/ from gunicorn (upstream production uses nginx for that);
# - minio: contentcuration.utils.minio_utils (bucket creation + public-read policy).
COPY requirements.txt /src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir whitenoise==5.2.0 minio==7.1.1

COPY . /src/

# Frontend production build (webpack --env prod): bundles go to
# contentcuration/contentcuration/static/studio/ with publicPath /static/studio/, and
# contentcuration/build/webpack-stats.json for django-webpack-loader.
# Studio's webpack build needs a lot of memory; exit code 137 (OOM kill) was seen on a Mac and on a
# Pi 5 with the default Node heap. Raise the heap; the Pi must have that much free RAM (+ swap).
ARG NODE_HEAP_MB=4096
RUN NODE_OPTIONS=--max-old-space-size=${NODE_HEAP_MB} yarn run build \
    && test -s contentcuration/build/webpack-stats.json

# Static files and translations at build time. idea_settings has AWS_AUTO_CREATE_BUCKET=False, so
# importing the settings does not contact MinIO; collectstatic/compilemessages need no database.
ENV DJANGO_SETTINGS_MODULE=contentcuration.idea_settings
# compilemessages runs from contentcuration/ so it does not walk /src/node_modules for locale dirs.
RUN python contentcuration/manage.py collectstatic --noinput \
    && (cd contentcuration && python manage.py compilemessages) \
    && test -d contentcuration/static/studio

ARG COMMIT_SHA
ENV RELEASE_COMMIT_SHA=$COMMIT_SHA

EXPOSE 8080

ENTRYPOINT ["python", "docker/idea-entrypoint.py"]
# Override the worker count on a small Pi with GUNICORN_CMD_ARGS (gunicorn reads it), e.g.
# GUNICORN_CMD_ARGS="--workers=2 --threads=4".
CMD ["gunicorn", "contentcuration.wsgi:application", "--chdir", "contentcuration", \
     "--bind", "0.0.0.0:8080", "--workers", "3", "--threads", "4", "--timeout", "600", \
     "--access-logfile", "-", "--error-logfile", "-"]
