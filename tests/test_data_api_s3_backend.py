from __future__ import annotations

from factor_factory.data_api.backends.s3_file import _s3_filesystem_kwargs


def test_s3_filesystem_kwargs_are_direct_by_default(monkeypatch):
    monkeypatch.delenv('FACTORFORGE_S3_PROXY_URL', raising=False)

    kwargs = _s3_filesystem_kwargs()

    assert 'proxy_options' not in kwargs
    assert kwargs['request_timeout'] == 60.0
    assert kwargs['connect_timeout'] == 10.0


def test_s3_filesystem_kwargs_accept_explicit_proxy(monkeypatch):
    monkeypatch.setenv('FACTORFORGE_S3_PROXY_URL', ' http://172.29.0.1:3128 ')

    kwargs = _s3_filesystem_kwargs()

    assert kwargs['proxy_options'] == 'http://172.29.0.1:3128'
