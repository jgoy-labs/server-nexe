"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/models.py
Description: str = Field(..., description="System description")

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict

class SystemResponse(BaseModel):
  """Response model for root endpoint (/)"""
  system: str = Field(..., description="System name")
  description: str = Field(..., description="System description")
  status: str = Field(..., description="System status")
  version: str = Field(..., description="System version")
  type: str = Field(..., description="Server type")

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "system": "Nexe 0.8",
        "description": "Module orchestration system operational",
        "status": "System ready and operational",
        "version": "0.9.0",
        "type": "basic_server"
      }
    }
  )

class HealthResponse(BaseModel):
  """Response model for health check endpoint (/health)"""
  status: str = Field(..., description="Health status")
  message: str = Field(..., description="Health message")
  version: str = Field(..., description="System version")
  uptime: str = Field(..., description="System uptime")

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "status": "operational",
        "message": "Basic server operational",
        "version": "0.9.0",
        "uptime": "operational"
      }
    }
  )

class EndpointInfo(BaseModel):
  """Information about a single endpoint"""
  path: str = Field(..., description="Endpoint path")
  method: str = Field(..., description="HTTP method")
  description: str = Field(..., description="Human-readable description of the endpoint functionality")

class ApiInfoResponse(BaseModel):
  """Response model for API info endpoint (/api/info)"""
  name: str = Field(..., description="API name")
  version: str = Field(..., description="API version")
  description: str = Field(..., description="API description")
  endpoints: List[EndpointInfo] = Field(..., description="Available endpoints")

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "name": "Nexe 0.8",
        "version": "0.9.0",
        "description": "Module orchestration system operational",
        "endpoints": [
          {
            "path": "/",
            "method": "GET",
            "description": "System root endpoint"
          },
          {
            "path": "/health",
            "method": "GET",
            "description": "System health check"
          }
        ]
      }
    }
  )

class ModuleInfo(BaseModel):
  """Information about a single module"""
  name: str = Field(..., description="Module name")
  status: str = Field(..., description="Module status")
  version: Optional[str] = Field(None, description="Module version")
  description: Optional[str] = Field(None, description="Module description")

class ModulesListResponse(BaseModel):
  """Response model for modules list endpoint (/modules)"""
  status: str = Field(..., description="Response status")
  data: Optional[Dict[str, Any]] = Field(None, description="Module integration statistics and metadata")
  message: Optional[str] = Field(None, description="Status or error message details")

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "status": "ok",
        "data": {
          "total_modules": 2,
          "total_routes": 10
        }
      }
    }
  )

class ModuleRoutesResponse(BaseModel):
  """Response model for module routes endpoint (/modules/{module_name}/routes)"""
  status: str = Field(..., description="Response status")
  module: Optional[str] = Field(None, description="Module name")
  routes: Optional[List[str]] = Field(None, description="List of routes")
  message: Optional[str] = Field(None, description="Status or error message details")

  model_config = ConfigDict(
    json_schema_extra={
      "example": {
        "status": "ok",
        "module": "security",
        "routes": ["/security/scan", "/security/report"]
      }
    }
  )