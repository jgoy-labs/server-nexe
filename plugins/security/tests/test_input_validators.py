"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/tests/test_input_validators.py
Description: Tests per validadors d'entrada. Detecta XSS, SQL injection, NoSQL injection, command injection, path traversal i LDAP injection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from fastapi import HTTPException

from plugins.security.core.input_validators import (
  sanitize_html,
  detect_xss_attempt,
  detect_sql_injection,
  detect_nosql_injection,
  detect_command_injection,
  detect_path_traversal,
  detect_ldap_injection,
  validate_string_input,
  validate_dict_input,
  validate_content_type,
  validate_charset,
  validate_request_headers,
  validate_request_params,
  validate_request_path,
  validate_all_request_inputs,
)

def test_sanitize_html_escapes_tags() -> None:
  """Test that HTML tags are escaped."""
  result = sanitize_html("<script>alert('xss')</script>")
  assert "&lt;script&gt;" in result
  assert "&lt;/script&gt;" in result

def test_detect_xss_script_tag() -> None:
  """Test XSS detection with script tags."""
  assert detect_xss_attempt("<script>alert('xss')</script>") is True
  assert detect_xss_attempt("normal text") is False

def test_detect_xss_javascript_protocol() -> None:
  """Test XSS detection with javascript: protocol."""
  assert detect_xss_attempt("<a href='javascript:alert(1)'>click</a>") is True

def test_detect_xss_event_handlers() -> None:
  """Test XSS detection with event handlers."""
  assert detect_xss_attempt("<img src=x onerror='alert(1)'>") is True
  assert detect_xss_attempt("<div onclick='alert(1)'>") is True

def test_detect_xss_iframe() -> None:
  """Test XSS detection with iframe."""
  assert detect_xss_attempt("<iframe src='evil.com'></iframe>") is True

def test_detect_sql_union_select() -> None:
  """Test SQL injection detection with UNION SELECT."""
  assert detect_sql_injection("1' UNION SELECT * FROM users--") is True

def test_detect_sql_or_condition() -> None:
  """Test SQL injection detection with OR '1'='1'."""
  assert detect_sql_injection("admin' OR '1'='1") is True

def test_detect_sql_drop_table() -> None:
  """Test SQL injection detection with DROP TABLE."""
  assert detect_sql_injection("'; DROP TABLE users--") is True

def test_detect_sql_comment() -> None:
  """Test SQL injection detection with comments."""
  assert detect_sql_injection("admin'-- ") is True

def test_no_sql_injection_in_normal_text() -> None:
  """Test that normal text is not flagged as SQL injection."""
  assert detect_sql_injection("This is normal text") is False
  assert detect_sql_injection("user@example.com") is False

def test_detect_nosql_mongo_operators() -> None:
  """Test NoSQL injection detection with MongoDB operators."""
  malicious_data = {"username": "admin", "password": {"$ne": None}}
  assert detect_nosql_injection(malicious_data) is True

def test_detect_nosql_where_clause() -> None:
  """Test NoSQL injection detection with $where."""
  malicious_data = {"$where": "function() { return true; }"}
  assert detect_nosql_injection(malicious_data) is True

def test_detect_nosql_regex() -> None:
  """Test NoSQL injection detection with $regex."""
  malicious_data = {"username": {"$regex": ".*"}}
  assert detect_nosql_injection(malicious_data) is True

def test_no_nosql_injection_in_clean_data() -> None:
  """Test that clean data is not flagged."""
  clean_data = {"username": "john", "email": "john@example.com"}
  assert detect_nosql_injection(clean_data) is False

def test_detect_command_injection_semicolon() -> None:
  """Test command injection detection with semicolon."""
  assert detect_command_injection("file.txt; rm -rf /") is True

def test_detect_command_injection_pipe() -> None:
  """Test command injection detection with pipe."""
  assert detect_command_injection("file.txt | cat /etc/passwd") is True

def test_detect_command_injection_backticks() -> None:
  """Test command injection detection with backticks."""
  assert detect_command_injection("file.txt `whoami`") is True

def test_detect_command_injection_redirect() -> None:
  """Test command injection detection with redirect."""
  assert detect_command_injection("file.txt > /etc/shadow") is True

def test_no_command_injection_in_normal_filename() -> None:
  """Test that normal filenames are not flagged."""
  assert detect_command_injection("document.pdf") is False
  assert detect_command_injection("my-file_2023.txt") is False

def test_detect_path_traversal_double_dot() -> None:
  """Test path traversal detection with ../ """
  assert detect_path_traversal("../../etc/passwd") is True

def test_detect_path_traversal_encoded() -> None:
  """Test path traversal detection with URL-encoded ../ """
  assert detect_path_traversal("%2e%2e/etc/passwd") is True

def test_detect_path_traversal_absolute() -> None:
  """Test path traversal detection with absolute paths."""
  assert detect_path_traversal("/etc/passwd") is True

def test_no_path_traversal_in_normal_path() -> None:
  """Test that normal paths are not flagged."""
  assert detect_path_traversal("documents/report.pdf") is False
  assert detect_path_traversal("readme/README.md") is False

def test_detect_ldap_injection_wildcard() -> None:
  """Test LDAP injection detection with wildcard."""
  assert detect_ldap_injection("*)(uid=*))(|(uid=*") is True

def test_detect_ldap_injection_parentheses() -> None:
  """Test LDAP injection detection with parentheses."""
  assert detect_ldap_injection("admin)(|(password=*)") is True

def test_no_ldap_injection_in_normal_username() -> None:
  """Test that normal usernames are not flagged."""
  assert detect_ldap_injection("john.doe") is False
  assert detect_ldap_injection("user123") is False

def test_validate_string_input_success() -> None:
  """Test that valid input passes validation."""
  result = validate_string_input("normal text", max_length=100)
  assert result == "normal text"

def test_validate_string_input_too_long() -> None:
  """Test that input exceeding max_length is rejected."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("x" * 101, max_length=100)
  assert exc_info.value.status_code == 400
  assert "too long" in exc_info.value.detail

def test_validate_string_input_xss_blocked() -> None:
  """Test that XSS attempt is blocked."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("<script>alert('xss')</script>")
  assert exc_info.value.status_code == 400
  assert "XSS" in exc_info.value.detail

def test_validate_string_input_sql_blocked() -> None:
  """Test that SQL injection is blocked."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("1' UNION SELECT * FROM users--")
  assert exc_info.value.status_code == 400
  assert "SQL" in exc_info.value.detail

def test_validate_string_input_command_blocked() -> None:
  """Test that command injection is blocked."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("file.txt; rm -rf /")
  assert exc_info.value.status_code == 400
  assert "command injection" in exc_info.value.detail

def test_validate_dict_input_success() -> None:
  """Test that valid dict passes validation."""
  clean_data = {"username": "john", "email": "john@example.com"}
  result = validate_dict_input(clean_data)
  assert result == clean_data

def test_validate_dict_input_nosql_blocked() -> None:
  """Test that NoSQL injection in dict is blocked."""
  malicious_data = {"username": "admin", "password": {"$ne": None}}
  with pytest.raises(HTTPException) as exc_info:
    validate_dict_input(malicious_data)
  assert exc_info.value.status_code == 400
  assert "NoSQL" in exc_info.value.detail

def test_validate_content_type_valid_json() -> None:
  """Test that valid JSON content type is accepted."""
  assert validate_content_type("application/json", "POST") is True

def test_validate_content_type_valid_form() -> None:
  """Test that valid form content type is accepted."""
  assert validate_content_type("application/x-www-form-urlencoded", "POST") is True

def test_validate_content_type_valid_multipart() -> None:
  """Test that valid multipart content type is accepted."""
  assert validate_content_type("multipart/form-data", "POST") is True

def test_validate_content_type_with_charset() -> None:
  """Test that content type with charset is accepted."""
  assert validate_content_type("application/json; charset=utf-8", "POST") is True

def test_validate_content_type_empty_for_get() -> None:
  """Test that empty content type is accepted for GET."""
  assert validate_content_type("", "GET") is True

def test_validate_content_type_invalid() -> None:
  """Test that invalid content type is rejected."""
  with pytest.raises(HTTPException) as exc_info:
    validate_content_type("application/octet-stream", "POST")
  assert exc_info.value.status_code == 415
  assert "Unsupported Media Type" in exc_info.value.detail

def test_validate_charset_valid_utf8() -> None:
  """Test that valid UTF-8 charset is accepted."""
  assert validate_charset("application/json; charset=utf-8") is True

def test_validate_charset_valid_iso() -> None:
  """Test that valid ISO-8859-1 charset is accepted."""
  assert validate_charset("text/plain; charset=iso-8859-1") is True

def test_validate_charset_no_charset() -> None:
  """Test that content type without charset is accepted."""
  assert validate_charset("application/json") is True

def test_validate_charset_invalid() -> None:
  """Test that invalid charset is rejected."""
  with pytest.raises(HTTPException) as exc_info:
    validate_charset("application/json; charset=invalid-charset")
  assert exc_info.value.status_code == 415
  assert "Unsupported charset" in exc_info.value.detail

def test_validate_charset_malformed() -> None:
  """Test that malformed charset is rejected."""
  with pytest.raises(HTTPException) as exc_info:
    validate_charset("application/json; charset=")
  assert exc_info.value.status_code in [400, 415]

class MockRequest:
  """Mock FastAPI Request for testing."""
  def __init__(self, method="GET", path="/", headers=None, query_params=None):
    from fastapi.datastructures import Headers
    self.method = method
    self.url = type('obj', (object,), {'path': path})()
    self.headers = Headers(headers or {})
    self.query_params = query_params or {}
    self.client = type('obj', (object,), {'host': '120.8.0.1'})()

@pytest.mark.asyncio
async def test_validate_request_headers_valid_post() -> None:
  """Test that valid POST headers are accepted."""
  request = MockRequest(
    method="POST",
    headers={"content-type": "application/json; charset=utf-8"}
  )
  assert await validate_request_headers(request) is True

@pytest.mark.asyncio
async def test_validate_request_headers_get_no_content_type() -> None:
  """Test that GET without content-type is accepted."""
  request = MockRequest(method="GET")
  assert await validate_request_headers(request) is True

@pytest.mark.asyncio
async def test_validate_request_headers_invalid_content_type() -> None:
  """Test that invalid content type is rejected."""
  request = MockRequest(
    method="POST",
    headers={"content-type": "application/octet-stream"}
  )
  with pytest.raises(HTTPException) as exc_info:
    await validate_request_headers(request)
  assert exc_info.value.status_code == 415

@pytest.mark.asyncio
async def test_validate_request_path_valid() -> None:
  """Test that valid path is accepted."""
  request = MockRequest(path="/api/users")
  assert await validate_request_path(request) is True

@pytest.mark.asyncio
async def test_validate_request_path_traversal_attempt() -> None:
  """Test that path traversal is rejected."""
  request = MockRequest(path="/api/../../etc/passwd")
  with pytest.raises(HTTPException) as exc_info:
    await validate_request_path(request)
  assert exc_info.value.status_code == 400
  assert "Invalid path" in exc_info.value.detail

@pytest.mark.asyncio
async def test_validate_request_params_valid() -> None:
  """Test that valid query params are accepted."""
  request = MockRequest(query_params={"name": "test", "page": "1"})
  assert await validate_request_params(request) is True

@pytest.mark.asyncio
async def test_validate_request_params_xss_attempt() -> None:
  """Test that XSS in query params is rejected."""
  request = MockRequest(query_params={"search": "<script>alert(1)</script>"})
  with pytest.raises(HTTPException) as exc_info:
    await validate_request_params(request)
  assert exc_info.value.status_code == 400

@pytest.mark.asyncio
async def test_validate_request_params_sql_injection() -> None:
  """Test that SQL injection in query params is rejected."""
  request = MockRequest(query_params={"id": "1' OR '1'='1"})
  with pytest.raises(HTTPException) as exc_info:
    await validate_request_params(request)
  assert exc_info.value.status_code == 400

@pytest.mark.asyncio
async def test_validate_request_params_command_injection() -> None:
  """Test that command injection in query params is rejected."""
  request = MockRequest(query_params={"file": "test; rm -rf /"})
  with pytest.raises(HTTPException) as exc_info:
    await validate_request_params(request)
  assert exc_info.value.status_code == 400

@pytest.mark.asyncio
async def test_validate_all_request_inputs_valid() -> None:
  """Test that completely valid request is accepted."""
  request = MockRequest(
    method="POST",
    path="/api/users",
    headers={"content-type": "application/json"},
    query_params={"page": "1"}
  )
  assert await validate_all_request_inputs(request) is True

@pytest.mark.asyncio
async def test_validate_all_request_inputs_invalid_path() -> None:
  """Test that request with invalid path is rejected."""
  request = MockRequest(
    method="POST",
    path="/api/../../../etc/passwd",
    headers={"content-type": "application/json"}
  )
  with pytest.raises(HTTPException):
    await validate_all_request_inputs(request)

@pytest.mark.asyncio
async def test_validate_all_request_inputs_invalid_params() -> None:
  """Test that request with invalid params is rejected."""
  request = MockRequest(
    method="POST",
    path="/api/users",
    headers={"content-type": "application/json"},
    query_params={"search": "admin' OR '1'='1"}
  )
  with pytest.raises(HTTPException):
    await validate_all_request_inputs(request)