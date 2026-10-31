from flask import Flask

from services import storage


CHUNK_BYTES = 1024 * 1024


class _Stat:
    def __init__(self, size):
        self.size = size


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self._offset = 0
        self.read_sizes = []
        self.closed = False
        self.released = False

    def read(self, amount=None):
        self.read_sizes.append(amount)
        if self._offset >= len(self._payload):
            return b''
        if amount is None:
            amount = len(self._payload) - self._offset
        chunk = self._payload[self._offset:self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _Client:
    def __init__(self, response):
        self.response = response
        self.get_calls = []

    def stat_object(self, _bucket, _key):
        return _Stat(len(self.response._payload))

    def get_object(self, _bucket, _key, offset=0, length=0):
        self.get_calls.append((offset, length))
        return self.response


def test_open_ended_minio_range_is_streamed_in_chunks(tmp_path, monkeypatch):
    """A browser's bytes=0- request must not be buffered before playback starts."""
    payload = b'x' * (CHUNK_BYTES * 2 + 17)
    response = _Response(payload)
    client = _Client(response)
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    monkeypatch.setattr(storage, '_get_client', lambda: client)

    with app.app_context():
        result = storage.stream_media_range('courses/demo/video.mp4', 'bytes=0-')

    assert result['status'] == 206
    assert result['headers']['Content-Length'] == str(len(payload))
    assert client.get_calls == [(0, len(payload))]
    assert response.read_sizes == []
    assert response.closed is False

    body = iter(result['body'])
    assert next(body) == payload[:CHUNK_BYTES]
    assert response.read_sizes == [CHUNK_BYTES]
    assert b''.join(body) == payload[CHUNK_BYTES:]
    assert response.closed is True
    assert response.released is True


def test_unconsumed_minio_stream_releases_connection_when_closed(tmp_path, monkeypatch):
    """HEAD requests and pre-first-byte cancellations must not leak MinIO connections."""
    response = _Response(b'x' * CHUNK_BYTES)
    client = _Client(response)
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    monkeypatch.setattr(storage, '_get_client', lambda: client)

    with app.app_context():
        result = storage.stream_media_range('courses/demo/video.mp4', 'bytes=0-')

    body = result['body']
    body.close()

    assert response.read_sizes == []
    assert response.closed is True
    assert response.released is True
