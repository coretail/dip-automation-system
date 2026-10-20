"""Auth matrix smoke tests for protected routes."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, follow_redirects=False)


PROTECTED_ROUTES = [
    "/",
    "/admin/users",
    "/admin/trash",
    "/admin/company-documents",
    "/brands",
    "/sample-submissions",
    "/raw-materials",
    "/purchase-orders",
    "/notes",
    "/products/00000000-0000-0000-0000-000000000000/edit",
]


def test_anonymous_requests_are_redirected_or_denied():
    for path in PROTECTED_ROUTES:
        response = client.get(path)
        assert response.status_code in (303, 401, 403), (path, response.status_code)
        if response.status_code == 303:
            location = response.headers.get("location", "")
            assert "/login" in location, (path, location)
