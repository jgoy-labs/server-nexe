"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/specialists/trasher_specialist.py
Description: Specialist for trasher_manager — reports storage of the security module.

STUB — Functional in Part 2 when trasher_manager arrives from NAT7.

Contract:
  - trasher_manager calls get_storage_report()
  - Returns dict with paths, size, retention, cleanable
  - The plugin does not know who is asking, it only responds

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class SecurityTrasherSpecialist:
    """Specialist for trasher_manager. Stub until Part 2."""

    def get_storage_report(self):
        """Returns storage report for trasher_manager."""
        raise NotImplementedError("Stub — functional in Part 2")
