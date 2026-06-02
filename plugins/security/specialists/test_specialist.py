"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/specialists/test_specialist.py
Description: Specialist for test_manager — reports tests of the security module.

STUB — Functional in Part 2 when test_manager arrives.

Contract:
  - test_manager calls get_test_report()
  - Returns dict with test_count, passed, failed, coverage
  - The plugin does not know who is asking, it only responds

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class SecurityTestSpecialist:
    """Specialist for test_manager. Stub until Part 2."""

    def get_test_report(self):
        """Returns test report for test_manager."""
        raise NotImplementedError("Stub — functional in Part 2")
