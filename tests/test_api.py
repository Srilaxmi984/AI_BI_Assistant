import pytest
from fastapi.testclient import TestClient
from src.api import app

@pytest.fixture(scope="module")
def client():
    return TestClient(app)

def test_api_health(client):
    """Test health check endpoint."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"

def test_api_kpis(client):
    """Test KPI endpoint returns valid aggregated metrics."""
    res = client.get("/api/kpis")
    assert res.status_code == 200
    data = res.json()
    assert data["total_revenue"] == 1445200.0
    assert data["top_product"] == "Monitor"
    assert data["top_region"] == "South"

def test_api_query_endpoint(client):
    """Test /api/query endpoint with benchmark question."""
    res = client.post("/api/query", json={"question": "What is the total revenue?"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "1,445,200.00" in data["answer"]
    assert "supporting_figures" in data

def test_api_data_quality_endpoint(client):
    """Test /api/data-quality returns audit logs."""
    res = client.get("/api/data-quality")
    assert res.status_code == 200
    data = res.json()
    assert data["total_issues_logged"] >= 3

def test_api_invalid_request_handling(client):
    """Test validation error on empty payload."""
    res = client.post("/api/query", json={"question": ""})
    assert res.status_code == 422 # Pydantic min_length validation error
