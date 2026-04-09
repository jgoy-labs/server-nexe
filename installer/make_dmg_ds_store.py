#!/usr/bin/env python3
"""
Crea el .DS_Store per al DMG amb background i posicions d'icones.
Requereix: pip install ds_store mac_alias (instal·lat al sistema, no al bundle)

Ús: python3 make_dmg_ds_store.py <mount_point> <app_name>
Ex: python3 make_dmg_ds_store.py "/Volumes/Install Nexe" "InstallNexe"
"""
import sys
import os

# Afegir path del sistema per trobar ds_store instal·lat via pip3
sys.path.insert(0, '/Users/jgoy/Library/Python/3.9/lib/python/site-packages')

try:
    import ds_store
    from mac_alias import Alias
except ImportError:
    print("[WARN] ds_store/mac_alias no disponibles — saltant DS_Store", flush=True)
    sys.exit(0)

def make_ds_store(mount_point, app_name):
    ds_path = os.path.join(mount_point, '.DS_Store')
    bg_path = os.path.join(mount_point, '.background', 'background.png')

    if not os.path.exists(bg_path):
        print(f"[WARN] Background no trobat: {bg_path}", flush=True)
        sys.exit(0)

    # Crear alias per al background (format que Finder entén)
    bg_alias = Alias.for_file(bg_path)

    app_entry = app_name + '.app'

    with ds_store.DSStore.open(ds_path, 'w+') as store:
        # Configuració de la carpeta arrel
        store['.']['Iloc'] = ds_store.IlocT(x=0, y=0)  # no usada per carpetes
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
        # Vista: icones, sense ordenació automàtica
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
        # Posició de la icona de l'app — ⚠️ NO CANVIAR sense revisar el background (520x400)
        store[app_entry]['Iloc'] = ds_store.IlocT(x=260, y=145)

    print(f"[OK] .DS_Store creat: {ds_path}", flush=True)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Ús: make_dmg_ds_store.py <mount_point> <app_name>")
        sys.exit(1)
    make_ds_store(sys.argv[1], sys.argv[2])
