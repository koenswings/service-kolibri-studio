"""
IDEA URLs: contentcuration.urls plus /content/<path> served from the App's MinIO bucket.

With RUN_MODE=k8s, models.generate_storage_url() returns same-origin /content/... URLs (upstream
k8s proxies them with nginx, deploy/nginx.conf.jinja2). In docker-compose mode Studio returns
http://localhost:9000/... instead, which only works for a browser on the host itself, and
dev_urls.file_server redirects to <host>:9000, which needs MinIO published on a fixed host port.
This view streams the object from MinIO instead, so no MinIO port is published.
Uploads take the same route the other way: /content-upload/ (utils/idea_upload.py).
"""
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import Http404
from django.http import HttpResponseNotAllowed
from django.http import StreamingHttpResponse
from django.urls import re_path

from .urls import urlpatterns
from .utils.idea_upload import content_upload

CHUNK_SIZE = 64 * 1024
PASS_HEADERS = ("Content-Type", "Content-Length", "ETag", "Last-Modified", "Accept-Ranges", "Content-Range")


def content_from_storage(request, storage_path):
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET", "HEAD"])
    client = default_storage.s3_connection
    params = {"Bucket": settings.AWS_S3_BUCKET_NAME, "Key": storage_path}
    if request.META.get("HTTP_RANGE"):
        # Video/audio seeking.
        params["Range"] = request.META["HTTP_RANGE"]
    try:
        if request.method == "HEAD":
            obj = client.head_object(**params)
        else:
            obj = client.get_object(**params)
    except client.exceptions.NoSuchKey:
        raise Http404(storage_path)
    except Exception as e:  # botocore ClientError: 404 on HEAD, 416, ...
        code = getattr(e, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in (403, 404):
            raise Http404(storage_path)
        raise
    status = obj.get("ResponseMetadata", {}).get("HTTPStatusCode", 200)
    body = obj["Body"].iter_chunks(CHUNK_SIZE) if request.method == "GET" else iter(())
    response = StreamingHttpResponse(body, status=status)
    headers = obj.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    for name in PASS_HEADERS:
        value = headers.get(name.lower())
        if value:
            response[name] = value
    return response


urlpatterns = urlpatterns + [
    # Same-origin presigned PUT uploads, proxied to MinIO with the signed Host (utils/idea_upload.py).
    re_path(r"^content-upload/(?P<upload_path>.+)$", content_upload, name="idea_content_upload"),
    re_path(r"^content/(?P<storage_path>.+)$", content_from_storage, name="idea_content"),
]
