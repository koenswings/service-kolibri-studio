"""
Same-origin upload path for IDEA (koenswings/app-kolibri-studio#2).

Studio uploads a file in two steps: the browser asks Studio for a presigned PUT URL
(viewsets/file.py upload_url -> utils/storage_common.get_presigned_upload_url) and then PUTs the
file to that URL itself (frontend shared/vuex/file/actions.js uploadFileToStorage). With MinIO,
boto3 signs the URL for AWS_S3_ENDPOINT_URL, the internal compose address
(http://minio:9000/<bucket>/<key>?X-Amz-...), which a browser on the LAN cannot reach.

The fix keeps the signature valid without exposing MinIO:
  1. same_origin_upload_url() rewrites the presigned URL to a relative, same-origin URL:
     http://minio:9000/content/storage/a/b/f.mp4?X-Amz-... -> /content-upload/content/storage/a/b/f.mp4?X-Amz-...
     Only the scheme and host are dropped; the path and the query (with the signature) stay byte for byte.
  2. content_upload() (mounted at /content-upload/ by idea_urls.py) rebuilds the exact signed URL
     (upstream_upload_url(): endpoint + the same path + the same raw query) and streams the request
     body to it. requests sends Host = the endpoint's host, which is the host boto3 signed
     (X-Amz-SignedHeaders=host), so MinIO accepts the signature.

The signature itself is the authorisation (as with a direct PUT to S3): the view is CSRF-exempt, takes
only PUT, only paths inside the Studio bucket, and only URLs that carry an X-Amz-Signature.
"""
from urllib.parse import parse_qs
from urllib.parse import urlsplit

UPLOAD_PREFIX = "/content-upload/"
FORWARD_HEADERS = (
    # (WSGI META key, header name)
    ("CONTENT_TYPE", "Content-Type"),
    ("HTTP_CONTENT_MD5", "Content-MD5"),
)
CHUNK_SIZE = 64 * 1024


class UploadPathError(ValueError):
    pass


def same_origin_upload_url(presigned_url, endpoint_url, prefix=UPLOAD_PREFIX):
    """Relative same-origin URL for a presigned PUT URL signed for `endpoint_url`."""
    u = urlsplit(presigned_url)
    e = urlsplit(endpoint_url)
    if (u.scheme, u.netloc) != (e.scheme, e.netloc):
        raise UploadPathError("presigned URL is not on the storage endpoint")
    if not u.path.startswith("/"):
        raise UploadPathError("presigned URL has no path")
    return prefix.rstrip("/") + u.path + ("?" + u.query if u.query else "")


def upstream_upload_url(endpoint_url, raw_path, raw_query, bucket, prefix=UPLOAD_PREFIX):
    """
    The presigned URL that `same_origin_upload_url` turned into `raw_path?raw_query`.

    `raw_path` / `raw_query` are as the client sent them (still percent-encoded), so the
    canonical request MinIO computes is the one boto3 signed.
    """
    head = prefix.rstrip("/")
    if not raw_path.startswith(head + "/"):
        raise UploadPathError("not an upload path")
    path = raw_path[len(head):]
    if not path.startswith("/{}/".format(bucket)) or len(path) <= len(bucket) + 2:
        raise UploadPathError("upload path is outside the storage bucket")
    if any(seg in ("..", ".") for seg in path.split("/")) or "\\" in path:
        raise UploadPathError("upload path has dot segments")
    if not parse_qs(raw_query).get("X-Amz-Signature"):
        raise UploadPathError("upload URL is not presigned")
    return endpoint_url.rstrip("/") + path + "?" + raw_query


class _Body(object):
    """The request body as a sized stream, so requests sends Content-Length and not chunked."""

    def __init__(self, stream, length):
        self.stream = stream
        self.length = length

    def __len__(self):
        return self.length

    def read(self, size=-1):
        return self.stream.read(CHUNK_SIZE if size is None or size < 0 else size)

    def __iter__(self):
        while True:
            chunk = self.stream.read(CHUNK_SIZE)
            if not chunk:
                return
            yield chunk


def proxy_put(target_url, stream, length, headers, timeout=(10, 900)):
    """PUT `length` bytes of `stream` to `target_url`; returns the requests.Response."""
    import requests

    headers = dict(headers)
    headers["Content-Length"] = str(length)
    return requests.put(
        target_url, data=_Body(stream, length), headers=headers, timeout=timeout, allow_redirects=False
    )


def content_upload(request, upload_path=None):
    """Django view for PUT /content-upload/<bucket>/<key>?X-Amz-... (see module docstring)."""
    from django.conf import settings
    from django.http import HttpResponse
    from django.http import HttpResponseBadRequest
    from django.http import HttpResponseNotAllowed

    if request.method != "PUT":
        return HttpResponseNotAllowed(["PUT"])
    # gunicorn passes the request target unaltered in RAW_URI; fall back to Django's re-quoted path.
    raw = request.META.get("RAW_URI") or request.get_full_path()
    raw_path, _, raw_query = raw.partition("?")
    try:
        target = upstream_upload_url(
            settings.AWS_S3_ENDPOINT_URL, raw_path, raw_query, settings.AWS_S3_BUCKET_NAME
        )
    except UploadPathError as e:
        return HttpResponseBadRequest(str(e))
    try:
        length = int(request.META.get("CONTENT_LENGTH") or "")
    except ValueError:
        return HttpResponse("Content-Length required", status=411)
    headers = {name: request.META[key] for key, name in FORWARD_HEADERS if request.META.get(key)}
    upstream = proxy_put(target, request, length, headers)
    response = HttpResponse(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/xml"),
    )
    if upstream.headers.get("ETag"):
        response["ETag"] = upstream.headers["ETag"]
    return response


content_upload.csrf_exempt = True
