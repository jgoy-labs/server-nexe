"""
Tests per core/models.py - tots els models Pydantic
"""
import pytest
from core.models import (
    SystemResponse,
    HealthResponse,
    EndpointInfo,
    ApiInfoResponse,
    ModuleInfo,
    ModulesListResponse,
    ModuleRoutesResponse,
)


class TestSystemResponse:
    def test_creation_with_all_fields(self):
        r = SystemResponse(
            system="Nexe 0.9",
            description="Descripció",
            status="operatiu",
            version="0.9.1",
            type="servidor_bàsic"
        )
        assert r.system == "Nexe 0.9"
        assert r.description == "Descripció"
        assert r.status == "operatiu"
        assert r.version == "0.9.1"
        assert r.type == "servidor_bàsic"

    def test_serialization(self):
        r = SystemResponse(
            system="Nexe", description="d", status="s", version="v", type="t"
        )
        data = r.model_dump()
        assert "system" in data
        assert "description" in data
        assert "status" in data
        assert "version" in data
        assert "type" in data

    def test_missing_required_field_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            SystemResponse(system="Nexe")  # falten camps requerits


class TestHealthResponse:
    def test_creation(self):
        r = HealthResponse(
            status="operatiu",
            message="Servidor operatiu",
            version="0.9.1",
            uptime="operacional"
        )
        assert r.status == "operatiu"
        assert r.message == "Servidor operatiu"
        assert r.version == "0.9.1"
        assert r.uptime == "operacional"

    def test_serialization(self):
        r = HealthResponse(status="s", message="m", version="v", uptime="u")
        data = r.model_dump()
        assert set(data.keys()) == {"status", "message", "version", "uptime"}


class TestEndpointInfo:
    def test_creation(self):
        e = EndpointInfo(path="/health", method="GET", description="Health check")
        assert e.path == "/health"
        assert e.method == "GET"
        assert e.description == "Health check"

    def test_required_fields(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            EndpointInfo(path="/health")  # falten method i description


class TestApiInfoResponse:
    def test_creation_with_endpoints(self):
        endpoints = [
            EndpointInfo(path="/", method="GET", description="Arrel"),
            EndpointInfo(path="/health", method="GET", description="Salut"),
        ]
        r = ApiInfoResponse(
            name="Nexe 0.9",
            version="0.9.1",
            description="Descripció API",
            endpoints=endpoints
        )
        assert r.name == "Nexe 0.9"
        assert len(r.endpoints) == 2
        assert r.endpoints[0].path == "/"

    def test_empty_endpoints_list(self):
        r = ApiInfoResponse(
            name="N", version="v", description="d", endpoints=[]
        )
        assert r.endpoints == []

    def test_serialization(self):
        r = ApiInfoResponse(
            name="N", version="v", description="d",
            endpoints=[EndpointInfo(path="/", method="GET", description="Root")]
        )
        data = r.model_dump()
        assert "endpoints" in data
        assert isinstance(data["endpoints"], list)


class TestModuleInfo:
    def test_creation_required_fields(self):
        m = ModuleInfo(name="security", status="active")
        assert m.name == "security"
        assert m.status == "active"
        assert m.version is None
        assert m.description is None

    def test_creation_with_optional_fields(self):
        m = ModuleInfo(
            name="security",
            status="active",
            version="1.0.0",
            description="Security module"
        )
        assert m.version == "1.0.0"
        assert m.description == "Security module"


class TestModulesListResponse:
    def test_creation_with_data(self):
        r = ModulesListResponse(
            status="correcte",
            data={"total_modules": 3, "total_routes": 15}
        )
        assert r.status == "correcte"
        assert r.data["total_modules"] == 3
        assert r.message is None

    def test_creation_with_error(self):
        r = ModulesListResponse(
            status="error",
            message="No inicialitzat"
        )
        assert r.status == "error"
        assert r.message == "No inicialitzat"
        assert r.data is None

    def test_serialization(self):
        r = ModulesListResponse(status="ok", data={"k": "v"})
        data = r.model_dump()
        assert data["status"] == "ok"
        assert data["data"] == {"k": "v"}


class TestModuleRoutesResponse:
    def test_creation_with_routes(self):
        r = ModuleRoutesResponse(
            status="correcte",
            module="security",
            routes=["/security/scan", "/security/report"]
        )
        assert r.status == "correcte"
        assert r.module == "security"
        assert len(r.routes) == 2

    def test_creation_with_error(self):
        r = ModuleRoutesResponse(
            status="error",
            message="No inicialitzat"
        )
        assert r.status == "error"
        assert r.message == "No inicialitzat"
        assert r.module is None
        assert r.routes is None

    def test_serialization(self):
        r = ModuleRoutesResponse(status="ok", module="m", routes=[])
        data = r.model_dump()
        assert "status" in data
        assert "module" in data
        assert "routes" in data
