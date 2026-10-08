from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix


def test_slash_redirect_respects_forwarded_https():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.route('/api/jobs/')
    def jobs():
        return {'ok': True}

    response = app.test_client().get(
        '/api/jobs',
        headers={
            'Host': '192.168.0.186:8443',
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': '192.168.0.186:8443',
        },
    )

    assert response.status_code == 308
    assert response.headers['Location'].startswith('https://192.168.0.186:8443/')
