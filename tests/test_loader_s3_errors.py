"""The loader reports presigned-S3 failures by step, HTTP status and S3 error code only."""

import io
import urllib.error

import pytest

from loader import main as lm


def _http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


def test_s3_error_code_parsed_from_xml():
    body = b"<?xml version='1.0'?><Error><Code>SignatureDoesNotMatch</Code><Message>x</Message></Error>"
    assert lm.s3_error_code(body) == "SignatureDoesNotMatch"
    assert lm.s3_error_code(b"not xml") == "unknown"
    assert lm.s3_error_code(b"") == "unknown"


def test_get_failure_names_step_status_and_code(monkeypatch):
    def boom(req, timeout):
        raise _http_error(403, b"<Error><Code>AccessDenied</Code></Error>")

    monkeypatch.setattr(lm.urllib.request, "urlopen", boom)
    with pytest.raises(lm.S3HttpError) as ei:
        lm.read_zip("https://bucket/raw.zip")
    assert ei.value.fields() == {
        "error": "S3HttpError",
        "step": "get_raw_zip",
        "status": 403,
        "s3_code": "AccessDenied",
    }


def test_put_failure_is_its_own_step(monkeypatch):
    def boom(req, timeout):
        raise _http_error(400, b"<Error><Code>InvalidRequest</Code></Error>")

    monkeypatch.setattr(lm.urllib.request, "urlopen", boom)
    with pytest.raises(lm.S3HttpError) as ei:
        lm.put_json("https://bucket/put", [{"a": 1}])
    assert ei.value.step == "put_labelled_set" and ei.value.status == 400


def test_main_prints_s3_fields_not_a_bare_type(monkeypatch, capsys):
    def boom(req, timeout):
        raise _http_error(403, b"<Error><Code>AccessDenied</Code></Error>")

    monkeypatch.setattr(lm.urllib.request, "urlopen", boom)
    monkeypatch.setattr(lm.settings, "PII_HMAC_KEY", "k", raising=False)
    rc = lm.main(["verify", "--zip-url", "https://bucket/raw.zip"])
    out = capsys.readouterr().out
    assert rc == 1
    assert '"step": "get_raw_zip"' in out and '"s3_code": "AccessDenied"' in out
