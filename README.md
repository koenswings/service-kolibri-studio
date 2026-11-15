# service-kolibri-studio
Build files for the Kolibri Studio service.

The source is a copy of [learningequality/studio](https://github.com/learningequality/studio) (see
`README.original`, `LICENSE.original`). The image is used by
[app-kolibri-studio](https://github.com/koenswings/app-kolibri-studio).

**Upstream version:** the copy is not the `v2024.12.03` tag. Its `package.json` is byte-identical
to upstream commit
[`53a2e6505f`](https://github.com/learningequality/studio/commit/53a2e6505f) (2025-01-24, on the
`unstable` and `hotfixes` branches), so image tags carry `2025.01.24`:
`koenswings/kolibri-studio:1.0-2025.01.24`.

## Production image (IDEA)

`Dockerfile` builds a production image (release blockers in koenswings/app-kolibri-studio#2):

- `yarn run build` (webpack `--env prod`, bundles under `/static/studio/`) and `collectstatic` +
  `compilemessages` run in the image build, so nothing is built at start.
- `gunicorn` serves Studio on `:8080`; `whitenoise` serves `/static/`. There is no webpack
  devserver, so no `:4000` port.
- Settings: `contentcuration.idea_settings` (DEBUG off, MinIO/S3 storage, console e-mail).
  `contentcuration.idea_urls` adds `/content/<path>`, streamed from MinIO; use it with
  `RUN_MODE=k8s`, so Studio links files as same-origin `/content/...` URLs.
- **Uploads, same origin:** Studio hands the browser a presigned PUT URL signed for the internal
  `http://minio:9000`. `utils/idea_upload.py` rewrites it to `/content-upload/<bucket>/<key>?<same query>`
  (`IDEA_SAME_ORIGIN_UPLOAD_PREFIX` in `idea_settings`), and the `/content-upload/` view streams the
  body to the exact signed URL, so `Host` is the signed host and MinIO accepts the signature. Only
  PUT, only the Studio bucket, only presigned URLs. Tests: `tests/utils/test_idea_upload.py` (an
  end-to-end case runs against a real MinIO/Silo when `IDEA_UPLOAD_E2E_ENDPOINT` is set).
- `docker/idea-entrypoint.py` waits for Postgres and MinIO, then:
  - creates the bucket and runs `createcachetable`, `migrate` and `loadconstants`;
  - sets the Site domain: `STUDIO_SITE_DOMAIN`, else `<IDEA_HOSTNAME>.local:<IDEA_APP_PORT>` (the
    Engine writes `IDEA_HOSTNAME` into every instance `.env`), else `localhost:<IDEA_APP_PORT>`;
  - creates one admin only if there is no admin yet: `STUDIO_ADMIN_EMAIL` / `STUDIO_ADMIN_PASSWORD`,
    defaults `admin@idea.local` / `admin911!`. IDEA also enables the login alias `admin` (the first
    active administrator), so the default login is `admin` / `admin911!`; registration and reset
    still require an e-mail. The credentials are never logged.
  - It does not add upstream's sample users and channels. `--no-prepare` as the first argument (or
    `IDEA_SKIP_PREPARE=1`; the celery worker) only waits for Postgres and MinIO.
- **Celery worker:** the same image with `make prodceleryworkers` (upstream command).
- `python` is in the image (`python:3.10-slim-bookworm`), so the App's `/healthz` healthcheck can use it.

Build on an ARM64 Pi:

```sh
docker buildx build --builder <throwaway-builder> --platform linux/arm64 --load \
  --build-arg COMMIT_SHA=$(git rev-parse HEAD) -t koenswings/kolibri-studio:1.0-2025.01.24 .
```

The webpack build needs a large Node heap (`NODE_HEAP_MB`, default 4096); with the default heap it
was killed with exit code 137 on a Mac and on a Pi 5.

The previous development image (`yarn run devserver`, sources built at start) is in git history
(`0a6b0a1`).
