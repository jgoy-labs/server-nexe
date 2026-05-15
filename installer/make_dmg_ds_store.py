#!/usr/bin/env python3
"""
Create the .DS_Store for the DMG with background and icon positions.
Requires: pip install ds_store mac_alias (installed system-wide, not in the bundle)

Usage: python3 make_dmg_ds_store.py <mount_point> <app_name>
Ex:    python3 make_dmg_ds_store.py "/Volumes/Install Nexe" "InstallNexe"
"""
import sys
import os

# Add system path to find ds_store installed via pip3
_user_site = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
if os.path.isdir(_user_site):
    sys.path.insert(0, _user_site)

try:
    import ds_store
    from mac_alias import Alias
except ImportError:
    print("[WARN] ds_store/mac_alias no disponibles — saltant DS_Store", flush=True)
    sys.exit(0)

def make_ds_store(mount_point, app_name):
    """Create a .DS_Store file with background image and icon layout for the DMG."""
    ds_path = os.path.join(mount_point, '.DS_Store')
    bg_path = os.path.join(mount_point, '.background', 'background.png')

    if not os.path.exists(bg_path):
        print(f"[WARN] Background not found: {bg_path}", flush=True)
        sys.exit(0)

    # Create alias for the background (format that Finder understands)
    bg_alias = Alias.for_file(bg_path)

    app_entry = app_name + '.app'

    with ds_store.DSStore.open(ds_path, 'w+') as store:
        # Root folder configuration
        store['.']['Iloc'] = ds_store.IlocT(x=0, y=0)  # not used for folders
        store['.']['bwsp'] = {
            'ShowStatusBar': False,
            'WindowBounds': '{{100, 100}, {520, 400}}',
            'ShowToolbar': False,
            'ShowTabView': False,
            'ShowPathbar': False,
            'ShowSidebar': False,
            'SidebarWidth': 0,
        }
        # Background (BKGD record)
        store['.']['BKGD'] = ds_store.BKGDAlias(bg_alias)
        # View: icons, no automatic sorting
        store['.']['icvp'] = {
            'arrangeBy': 'none',
            'backgroundColorBlue': 1.0,
            'backgroundColorGreen': 1.0,
            'backgroundColorRed': 1.0,
            'backgroundType': 2,  # 2 = picture
            'gridOffsetX': 0.0,
            'gridOffsetY': 0.0,
            'gridSpacing': 100.0,
            'iconSize': 128.0,
            'labelOnBottom': True,
            'scrollPositionX': 0.0,
            'scrollPositionY': 0.0,
            'showIconPreview': True,
            'textSize': 12.0,
            'viewOptionsVersion': 1,
        }
        # App icon position depends on the 520x400 background artwork.
        store[app_entry]['Iloc'] = ds_store.IlocT(x=260, y=145)

    print(f"[OK] .DS_Store created: {ds_path}", flush=True)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: make_dmg_ds_store.py <mount_point> <app_name>")
        sys.exit(1)
    make_ds_store(sys.argv[1], sys.argv[2])
