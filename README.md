# service-kolibri-studio
Build files for the Kolibri Studio service.

The source is a copy of [learningequality/studio](https://github.com/learningequality/studio) (see
`README.original`, `LICENSE.original`). The image is used by
[app-kolibri-studio](https://github.com/koenswings/app-kolibri-studio).

## Production image (IDEA)

`Dockerfile` builds a production image (release blockers in koenswings/app-kolibri-studio#2):

- `yarn run build` (webpack `--env prod`, bundles under `/static/studio/`) and `collectstatic` +
  `compilemessages` run in the image build, so nothing is built at start.
- `gunicorn` serves Studio on `:8080`; `whitenoise` serves `/static/`. There is no webpack
  devserver, so no `:4000` port.
- Settings: `contentcuration.idea_settings` (DEBUG off, MinIO/S3 storage, console e-mail).
  `contentcuration.idea_urls` adds `/content/<path>`, streamed from MinIO; use it with
  `RUN_MODE=k8s`, so Studio links files as same-origin `/content/...` URLs.
- `docker/idea-entrypoint.py` waits for Postgres and MinIO, creates the bucket, runs
  `createcachetable`, `migrate` and `loadconstants`, and creates one admin
  (`STUDIO_ADMIN_EMAIL` / `STUDIO_ADMIN_PASSWORD`) only if there is no admin yet. It does not add
  upstream's sample users and channels.
- `python` is in the image (`python:3.10-slim-bookworm`), so the App's `/healthz` healthcheck can use it.

Build on an ARM64 Pi:

```sh
docker buildx build --builder <throwaway-builder> --platform linux/arm64 --load \
  --build-arg COMMIT_SHA=$(git rev-parse HEAD) -t koenswings/kolibri-studio:<tag> .
```

The webpack build needs a large Node heap (`NODE_HEAP_MB`, default 4096); with the default heap it
was killed with exit code 137 on a Mac and on a Pi 5.

The previous development image (`yarn run devserver`, sources built at start) is in git history
(`0a6b0a1`).
