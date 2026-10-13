import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import Settings
from app.core.middleware import sanitize_url_prefix


client = TestClient(app)


class TestDefensiveUrlSanitization:
    """Test suite for URL prefix and APPLICATION_ROOT sanitization."""

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("https://example.com:8054/question-paper/", "/question-paper"),
            ("https://example.com:8054/question-paper", "/question-paper"),
            ("http://192.168.1.100:8050/my-app/", "/my-app"),
            ("http://sub.domain.org/nested/app/", "/nested/app"),
            ("/question-paper/", "/question-paper"),
            ("question-paper/", "/question-paper"),
            ("question-paper", "/question-paper"),
            ("/portal/exam", "/portal/exam"),
            ("https://example.com:8054", ""),
            ("https://example.com:8054/", ""),
            ("/", ""),
            ("", ""),
            (None, ""),
            ("///multiple///slashes///", "/multiple/slashes"),
        ]
    )
    def test_sanitize_url_prefix(self, input_val, expected):
        result = sanitize_url_prefix(input_val)
        assert result == expected
        assert not result.startswith("/http")
        assert not result.startswith("/https")
        if result:
            assert result.startswith("/")
            assert not result.endswith("/")

    def test_settings_model_validator_sync(self):
        settings_instance = Settings(
            APPLICATION_ROOT="https://example.com:8054/question-paper/",
            PUBLIC_ORIGIN="https://exam.domain.com:8443/",
            TRUSTED_PROXIES="127.0.0.1, 10.0.0.1, 172.16.0.0/16",
            MAX_UPLOAD_SIZE_MB="75",
            CORS_ORIGINS="https://frontend.domain.com, https://admin.domain.com"
        )
        assert settings_instance.APPLICATION_ROOT == "/question-paper"
        assert settings_instance.URL_PREFIX == "/question-paper"
        assert settings_instance.PUBLIC_ORIGIN == "https://exam.domain.com:8443"
        assert settings_instance.MAX_UPLOAD_SIZE_MB == 75
        assert settings_instance.MAX_FILE_SIZE_MB == 75
        assert settings_instance.TRUSTED_PROXIES == ["127.0.0.1", "10.0.0.1", "172.16.0.0/16"]
        assert settings_instance.CORS_ORIGINS == ["https://frontend.domain.com", "https://admin.domain.com"]


class TestRootDeployment:
    """Test standard deployment at domain root ('/')."""

    def test_root_index_html_served(self):
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert 'name="app-base"' in res.text
        assert "AI Question Paper Generator" in res.text

    def test_root_health_check(self):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert "application_root" in data
        assert "max_upload_size_mb" in data

    def test_root_swagger_docs(self):
        res = client.get("/docs")
        assert res.status_code == 200

    def test_root_openapi_json(self):
        res = client.get("/openapi.json")
        assert res.status_code == 200
        data = res.json()
        assert "paths" in data


class TestTrailingSlashRobustness:
    """Test that endpoints accept requests with or without trailing slash."""

    def test_health_with_and_without_trailing_slash(self):
        res_no_slash = client.get("/health")
        assert res_no_slash.status_code == 200

        res_with_slash = client.get("/health/")
        assert res_with_slash.status_code == 200
        assert res_with_slash.json()["status"] == "healthy"

    def test_api_config_with_and_without_trailing_slash(self):
        res_no_slash = client.get("/api/v1/config/llm")
        assert res_no_slash.status_code == 200

        res_with_slash = client.get("/api/v1/config/llm/")
        assert res_with_slash.status_code == 200
        assert "active_provider" in res_with_slash.json()


class TestReverseProxyPrefixHandling:
    """Test reverse proxy subpath prefix handling and header forwarding."""

    def test_prefixed_requests_with_forwarded_prefix_header(self):
        headers = {
            "x-forwarded-prefix": "/question-paper"
        }
        res = client.get("/health", headers=headers)
        assert res.status_code == 200
        assert res.json()["application_root"] == "/question-paper"

    def test_prefixed_path_rewriting_without_proxy_strip(self):
        """Simulates Nginx proxy_pass without trailing slash (path arrives with prefix)."""
        headers = {
            "x-forwarded-prefix": "/question-paper"
        }
        res = client.get("/question-paper/health", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_prefixed_trailing_slash_robustness(self):
        headers = {
            "x-forwarded-prefix": "/question-paper"
        }
        res = client.get("/question-paper/health/", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_prefixed_api_endpoint(self):
        headers = {
            "x-forwarded-prefix": "/question-paper"
        }
        res = client.get("/question-paper/api/v1/config/llm", headers=headers)
        assert res.status_code == 200
        assert "active_provider" in res.json()

    def test_prefixed_ui_serves_with_meta_app_base(self):
        headers = {
            "x-forwarded-prefix": "/question-paper"
        }
        res = client.get("/question-paper/", headers=headers)
        assert res.status_code == 200
        assert '<meta name="app-base" content="/question-paper">' in res.text
        assert 'basePath: "/question-paper"' in res.text

    def test_reverse_proxy_redirect_preservation(self):
        """
        Verify redirects do NOT downgrade https to http, do NOT point to localhost,
        and preserve prefix.
        """
        headers = {
            "x-forwarded-proto": "https",
            "x-forwarded-host": "exam.school.edu:8443",
            "x-forwarded-prefix": "/question-paper",
            "host": "backend:8050"
        }
        # Request /index redirect
        res = client.get("/question-paper/index", headers=headers, follow_redirects=False)
        assert res.status_code in [302, 307]
        location = res.headers.get("location", "")
        # Location must preserve /question-paper/ and not point to localhost
        assert "localhost" not in location
        assert location in ["/question-paper/", "https://exam.school.edu:8443/question-paper/"]


class TestFrontendAssetAndApiSanity:
    """Verify frontend HTML has dynamic helpers and no broken root-relative fetch calls."""

    def test_index_html_has_dynamic_api_helper(self):
        res = client.get("/")
        assert res.status_code == 200
        html = res.text
        # Assert helper function definitions
        assert "function getBasePath()" in html
        assert "function apiUrl(" in html
        assert 'id="link-docs"' in html
        # Assert no hardcoded non-apiUrl fetch calls for API endpoints
        assert "fetch('/api/v1/exam/markers'" not in html
        assert "fetch('/api/v1/exam-papers/generate-async'" not in html
        assert "fetch('/api/exam/generate-questions'" not in html
        assert "fetch('/api/v1/config/llm'" not in html
        assert "resolveStaticImages()" in html

    def test_prefixed_static_asset_serving(self):
        """Verify static files (brand logos) load correctly through reverse proxy prefix."""
        headers = {"x-forwarded-prefix": "/question-paper"}
        
        # Test prefixed URL
        res = client.get("/question-paper/static/Groq.png", headers=headers)
        assert res.status_code == 200
        assert "image/png" in res.headers["content-type"]

        # Test other logos
        for asset in ["chatgpt.png", "gemini.jpg", "nvidia.png"]:
            res = client.get(f"/question-paper/static/{asset}", headers=headers)
            assert res.status_code == 200
