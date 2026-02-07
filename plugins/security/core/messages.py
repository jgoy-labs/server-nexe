"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/messages.py
Description: i18n fallback messages for the security core.

www.jgoy.net
────────────────────────────────────
"""

FALLBACK_MESSAGES = {
  'security.auth.missing_key': 'Missing API key',
  'security.auth.invalid_key': 'Invalid API key',
  'security.auth.server_misconfigured': 'Server misconfiguration: NEXE_PRIMARY_API_KEY not configured. Set NEXE_PRIMARY_API_KEY environment variable.',
  'security.auth.key_not_configured': 'Server misconfiguration: API key not configured',
  'security.auth.server_misconfigured_no_valid_key': 'Server misconfiguration: No valid API key configured',
  'security.auth.dev_mode_localhost_only': 'DEV mode bypass only allowed from localhost',
  'security.auth.invalid_or_expired_key': 'Invalid or expired API key',
  'security.auth.dev_mode_bypass': 'DEV MODE: API key bypassed',
  'security.auth.dev_mode_warning': 'NOT for production!',
  'security.auth.primary_key_auth': 'Authenticated with primary API key',
  'security.auth.secondary_key_auth': 'Authenticated with secondary API key (deprecated)',
  'security.auth.secondary_key_action_required': 'MIGRATE TO PRIMARY KEY',

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

def get_message(i18n, key: str, fallback: str = None, **kwargs) -> str:
  """
  Get translated message or fallback.

  Args:
    i18n: i18n manager (can be None)
    key: Message key
    fallback: Optional fallback string
    **kwargs: Formatting arguments

  Returns:
    Formatted message
  """
  if i18n:
    try:
      value = i18n.t(key, **kwargs)
      if value != key:
        return value
    except Exception:
      pass

  template = fallback or FALLBACK_MESSAGES.get(key, key)
  try:
    return template.format(**kwargs)
  except KeyError:
    return template
