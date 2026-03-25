"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/specialists/trasher_specialist.py
Description: Specialist per trasher_manager — reporta storage del modul security.

STUB — Funcional a Part 2 quan arribi trasher_manager de NAT7.

Contracte:
  - trasher_manager crida get_storage_report()
  - Retorna dict amb paths, mida, retention, cleanable
  - El plugin no sap qui el pregunta, nomes respon

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class SecurityTrasherSpecialist:
    """Specialist per trasher_manager. Stub fins Part 2."""

    def get_storage_report(self):
        """Retorna informe de storage per trasher_manager."""
        raise NotImplementedError("Stub — funcional a Part 2")
