"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/specialists/test_specialist.py
Description: Specialist per test_manager — reporta tests del modul security.

STUB — Funcional a Part 2 quan arribi test_manager de NAT7.

Contracte:
  - test_manager crida get_test_report()
  - Retorna dict amb test_count, passed, failed, coverage
  - El plugin no sap qui el pregunta, nomes respon

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class SecurityTestSpecialist:
    """Specialist per test_manager. Stub fins Part 2."""

    def get_test_report(self):
        """Retorna informe de tests per test_manager."""
        raise NotImplementedError("Stub — funcional a Part 2")
