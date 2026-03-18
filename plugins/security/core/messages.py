"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/messages.py
Description: Missatges fallback i18n per security core.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'security.auth.missing_key': 'Missing API key',
  'security.auth.invalid_key': 'Invalid API key',
  'security.auth.server_misconfigured': 'Server misconfiguration: NEXE_ADMIN_API_KEY not configured. Set NEXE_ADMIN_API_KEY environment variable.',
  'security.auth.key_not_configured': 'Server misconfiguration: API key not configured',

  'security.validators.path_traversal': 'Invalid path: path traversal detected',
  'security.validators.file_not_found': 'File not found: {filename}',
  'security.validators.path_is_directory': 'Path is a directory, expected a file',
  'security.validators.invalid_path_format': 'Invalid path format: {error}',
  'security.validators.invalid_command_format': 'Invalid command format: {error}',
  'security.validators.empty_command': 'Empty command',
  'security.validators.command_not_allowed': "Command not allowed: '{command}'. Allowed: {allowed}",
  'security.validators.invalid_filename': "Invalid filename: contains dangerous pattern '{pattern}'",
  'security.validators.filename_too_long': 'Filename too long (max 255 characters)',
  'security.validators.endpoint_not_allowed': 'Endpoint not allowed. Allowed prefixes: {prefixes}',

  'security.sanitizers.input_not_string': 'Input must be a string',
  'security.sanitizers.input_too_long': 'Input too long (max: {max_length} chars)',
  'security.sanitizers.input_too_short': 'Input too short (min: {min_length} chars)',
  'security.sanitizers.xss_detected': 'Potentially malicious content detected (XSS)',
  'security.sanitizers.sql_injection_detected': 'Potentially malicious content detected (SQL)',
  'security.sanitizers.command_injection_detected': 'Potentially malicious content detected (command injection)',
  'security.sanitizers.path_traversal_detected': 'Potentially malicious content detected (path traversal)',
  'security.sanitizers.ldap_injection_detected': 'Potentially malicious content detected (LDAP)',
  'security.sanitizers.input_not_dict': 'Input must be a dictionary',
  'security.sanitizers.nosql_injection_detected': 'Potentially malicious content detected (NoSQL)',

  'security.request.invalid_header': 'Invalid request header: {header}',
  'security.request.content_type_header_invalid': 'Invalid Content-Type header',
  'security.request.content_type_not_allowed': 'Unsupported Media Type: Content-Type not allowed: {content_type}',
  'security.request.charset_not_allowed': 'Unsupported charset: {charset}',
  'security.request.invalid_query_param': 'Invalid query parameter: {param}',
  'security.request.validation_error': 'Internal validation error',
  'security.request.invalid_path': 'Invalid path',

  'security.logger.failed_log_event': 'Failed to log security event: {error}',
  'security.logger.failed_read_logs': 'Failed to read security logs: {error}',
  'security.logger.failed_read_file': 'Failed to read {file}: {error}',
  'security.logger.deleted_old_log': 'Deleted old security log: {filename}',
  'security.logger.failed_process_file': 'Failed to process {file}: {error}',
}

def get_message(i18n, key: str, **kwargs) -> str:
  """
  Obté missatge traduït o fallback.

  Args:
    i18n: Gestor i18n (pot ser None)
    key: Clau del missatge
    **kwargs: Arguments per format

  Returns:
    Missatge formatat
  """
  if i18n:
    return i18n.t(key, **kwargs)

  template = FALLBACK_MESSAGES.get(key, key)
  try:
    return template.format(**kwargs)
  except KeyError:
    return template