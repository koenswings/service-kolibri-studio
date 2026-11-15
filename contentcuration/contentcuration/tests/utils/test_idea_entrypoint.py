"""docker/idea-entrypoint.py site_domain(): loaded by file path, no database."""
import importlib.util
import os

import pytest

_PATH = os.getenv("IDEA_ENTRYPOINT") or os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "docker", "idea-entrypoint.py"
)
_spec = importlib.util.spec_from_file_location("idea_entrypoint_under_test", _PATH)
entrypoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(entrypoint)


@pytest.mark.parametrize(
    "env,want",
    [
        ({}, "localhost"),
        ({"IDEA_APP_PORT": "53082"}, "localhost:53082"),
        ({"IDEA_HOSTNAME": "idea03", "IDEA_APP_PORT": "53082"}, "idea03.local:53082"),
        ({"IDEA_HOSTNAME": "idea03", "STUDIO_SITE_DOMAIN": "studio.school.lan"}, "studio.school.lan"),
        ({"IDEA_HOSTNAME": " ", "IDEA_APP_PORT": ""}, "localhost"),
    ],
)
def test_site_domain(env, want):
    got = entrypoint.site_domain(env)
    assert got == want
    assert "learningequality" not in got


def test_entrypoint_source_never_logs_credentials():
    src = open(_PATH).read()
    assert "create_user(" not in src  # db_tools.create_user prints the password
    assert "STUDIO_ADMIN_PASSWORD" in src
    for line in src.splitlines():
        if "print(" in line or "logging." in line:
            assert "password" not in line.lower() or "STUDIO_ADMIN_PASSWORD" in line, line
