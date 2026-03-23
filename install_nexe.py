#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Version: 0.8.2
Author: Jordi Goy
Location: install_nexe.py
Description: Façade entry point — delegates to installer/install.py.
             (Patró façade del projecte, com core/app.py → core/server/factory.py)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from installer.install import run_installer


def main():
    run_installer()


if __name__ == '__main__':
    main()
