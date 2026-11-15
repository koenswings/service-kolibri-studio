"""
Tests for the IDEA same-origin upload path (utils/idea_upload.py).

No database. The module is loaded by file path, so these tests also run outside Studio's pytest
setup (any Django 3.2 + boto3 + requests). The end-to-end test talks to a real MinIO/Silo and is
skipped unless IDEA_UPLOAD_E2E_ENDPOINT is set, e.g. inside studio-app on a Pi:
  IDEA_UPLOAD_E2E_ENDPOINT=http://minio:9000 pytest contentcuration/contentcuration/tests/utils/test_idea_upload.py
"""
import hashlib
import importlib.util
import os
import threading
import uuid
from base64 import b64encode
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

import pytest
from django.test import RequestFactory
from django.test import override_settings

_PATH = os.getenv("IDEA_UPLOAD_MODULE") or os.path.join(os.path.dirname(__file__), "..", "..", "utils", "idea_upload.py")
_spec = importlib.util.spec_from_file_location("idea_upload_under_test", _PATH)
idea_upload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(idea_upload)

ENDPOINT = "http://minio:9000"
SIGNED = (
    "http://minio:9000/content/storage/a/b/ab12cd.mp4"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=development%2F20261115%2Fus-east-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20261115T090000Z&X-Amz-Expires=600&X-Amz-SignedHeaders=host&X-Amz-Signature=" + "0" * 64
)


def test_rewrite_keeps_path_and_query_byte_for_byte():
    rel = idea_upload.same_origin_upload_url(SIGNED, ENDPOINT)
    assert rel.startswith("/content-upload/content/storage/a/b/ab12cd.mp4?X-Amz-Algorithm=")
    path, _, query = rel.partition("?")
    assert idea_upload.upstream_upload_url(ENDPOINT, path, query, "content") == SIGNED


def test_rewrite_refuses_other_hosts():
    with pytest.raises(idea_upload.UploadPathError):
        idea_upload.same_origin_upload_url(SIGNED.replace("minio:9000", "evil:9000"), ENDPOINT)


@pytest.mark.parametrize(
    "path,query",
    [
        ("/content-upload/other-bucket/x", "X-Amz-Signature=1"),
        ("/content-upload/content/", "X-Amz-Signature=1"),
        ("/content-upload/content/storage/../../x", "X-Amz-Signature=1"),
        ("/content-upload/content/storage/a/b/x", "X-Amz-Date=1"),
        ("/content/content/storage/a/b/x", "X-Amz-Signature=1"),
    ],
)
def test_upstream_url_refuses(path, query):
    with pytest.raises(idea_upload.UploadPathError):
        idea_upload.upstream_upload_url(ENDPOINT, path, query, "content")


class _FakeS3(BaseHTTPRequestHandler):
    seen = {}

    def do_PUT(self):
        n = int(self.headers["Content-Length"])
        _FakeS3.seen.update(
            path=self.path, host=self.headers["Host"], body=self.rfile.read(n),
            md5=self.headers.get("Content-MD5"), ctype=self.headers.get("Content-Type"),
            chunked=self.headers.get("Transfer-Encoding"),
        )
        self.send_response(200)
        self.send_header("ETag", '"abc"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_s3():
    server = HTTPServer(("127.0.0.1", 0), _FakeS3)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:{}".format(server.server_port)
    server.shutdown()
    server.server_close()


def _put(url, body, **extra):
    return RequestFactory().generic("PUT", url, data=body, content_type="video/mp4", **extra)


def test_view_forwards_the_signed_request(fake_s3):
    signed = SIGNED.replace(ENDPOINT, fake_s3)
    rel = idea_upload.same_origin_upload_url(signed, fake_s3)
    body = os.urandom(200 * 1024)
    with override_settings(AWS_S3_ENDPOINT_URL=fake_s3, AWS_S3_BUCKET_NAME="content"):
        resp = idea_upload.content_upload(_put(rel, body, HTTP_CONTENT_MD5="bWQ1"))
    assert resp.status_code == 200 and resp["ETag"] == '"abc"'
    seen = _FakeS3.seen
    assert seen["host"] == fake_s3.split("//")[1]  # the host boto3 signed
    assert fake_s3 + seen["path"] == signed  # path + query unchanged
    assert seen["body"] == body and seen["md5"] == "bWQ1" and seen["ctype"] == "video/mp4"
    assert seen["chunked"] is None


def test_view_refuses_other_methods_and_paths():
    with override_settings(AWS_S3_ENDPOINT_URL=ENDPOINT, AWS_S3_BUCKET_NAME="content"):
        get = RequestFactory().get("/content-upload/content/storage/a/b/x?X-Amz-Signature=1")
        assert idea_upload.content_upload(get).status_code == 405
        bad = _put("/content-upload/other/x?X-Amz-Signature=1", b"x")
        assert idea_upload.content_upload(bad).status_code == 400


def test_view_is_csrf_exempt():
    assert getattr(idea_upload.content_upload, "csrf_exempt", False) is True


@pytest.mark.skipif(not os.getenv("IDEA_UPLOAD_E2E_ENDPOINT"), reason="needs a MinIO/Silo endpoint")
def test_end_to_end_against_minio():
    """Presign for the internal endpoint, upload through the view, read the object back."""
    import boto3
    from botocore.client import Config

    endpoint = os.environ["IDEA_UPLOAD_E2E_ENDPOINT"]
    bucket = os.getenv("IDEA_UPLOAD_E2E_BUCKET", "content")
    s3 = boto3.client(
        "s3", endpoint_url=endpoint, config=Config(signature_version="s3v4"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "development"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "development"),
        region_name="us-east-1",
    )
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
    key = "storage/e/2/e2e-{}.bin".format(uuid.uuid4().hex)
    body = os.urandom(3 * 1024 * 1024 + 17)
    signed = s3.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=600)
    rel = idea_upload.same_origin_upload_url(signed, endpoint)
    md5 = b64encode(hashlib.md5(body).digest()).decode()
    with override_settings(AWS_S3_ENDPOINT_URL=endpoint, AWS_S3_BUCKET_NAME=bucket):
        resp = idea_upload.content_upload(_put(rel, body, HTTP_CONTENT_MD5=md5))
        assert resp.status_code == 200, resp.content
        # A tampered signature must be refused by MinIO, through the same path.
        bad = rel.replace("X-Amz-Signature=", "X-Amz-Signature=0")
        assert idea_upload.content_upload(_put(bad, b"x")).status_code == 403
    assert s3.get_object(Bucket=bucket, Key=key)["Body"].read() == body
    s3.delete_object(Bucket=bucket, Key=key)
