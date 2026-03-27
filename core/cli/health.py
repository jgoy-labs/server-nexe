"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/health.py
Description: Health check interface for Central Nexe CLI. Facade that prevents imports

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .specialists.cli_specialist import check_cli_specialist

def get_health(i18n=None):
  """
  Get health status for the CLI Central Nexe module.

  This function acts as a facade to the specialist system,
  preventing circular imports between manifest.py and specialists.

  Args:
    i18n: Internationalization manager (optional)

  Returns:
    dict: Health check results in standardized format
      {
        "name": str,
        "status": str (HEALTHY|DEGRADED|UNHEALTHY),
        "checks": list[str],
        "details": list[dict]
      }
  """
  return check_cli_specialist(i18n=i18n)