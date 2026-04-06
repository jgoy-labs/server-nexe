"""
────────────────────────────────────
Server Nexe
Location: installer/tray_translations.py
Description: Translations and language detection for the tray app.
────────────────────────────────────
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

T = {
    "ca": {
        "start": "▶ Engegar servidor",
        "stop": "⏹ Aturar servidor",
        "status_running": "Servidor actiu",
        "status_stopped": "Servidor aturat",
        "open_ui": "🌐 Obrir Web UI",
        "open_logs": "📄 Obrir logs",
        "docs": "📖 Documentació",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Temps: {uptime}",
        "quit": "Sortir",
        "starting": "Engegant...",
        "stopping": "Aturant...",
        "settings": "⚙️ Configuració",
        "website": "🌐 server-nexe.com",
        "donate": "💚 Suportar el projecte",
        "uninstall": "🗑 Desinstal·lar Nexe",
        "uninstall_title": "Desinstal·lar Nexe",
        "uninstall_warning": "Això esborrarà TOTA la instal·lació de Nexe:\n\n• Models descarregats\n• Memòria i converses\n• Base de coneixement\n• Configuració\n\n{storage}\n\nAquesta acció NO es pot desfer.",
        "uninstall_confirm": "Estàs a punt d'esborrar Nexe i totes les seves dades permanentment.",
        "uninstall_checkbox": "Confirmo que vull esborrar-ho tot",
        "uninstall_done": "Nexe s'ha desinstal·lat correctament.\n\n{details}",
        "uninstall_partial": "Nexe s'ha aturat, però no s'ha pogut esborrar del tot.\n\n{details}\n\nEsborra manualment el que quedi.",
        "uninstall_storage": "Espai que s'alliberarà: {size}",
        "uninstall_removed": "Esborrat:",
        "uninstall_failed": "No s'ha pogut esborrar:",
        "uninstall_data_title": "Dades de Nexe",
        "uninstall_data_message": "Vols conservar les teves dades?\n\n• Converses i memòria\n• Base de coneixement\n• Configuració\n\nEs guardaran a ~/nexe-backup-[data]",
        "uninstall_keep_data": "Sí, conservar dades",
        "uninstall_delete_all": "No, esborrar tot",
        "uninstall_backup_ok": "Dades guardades a {path}",
        "uninstall_backup_failed": "No s'han pogut guardar les dades",
    },
    "es": {
        "start": "▶ Iniciar servidor",
        "stop": "⏹ Detener servidor",
        "status_running": "Servidor activo",
        "status_stopped": "Servidor detenido",
        "open_ui": "🌐 Abrir Web UI",
        "open_logs": "📄 Abrir logs",
        "docs": "📖 Documentación",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Tiempo: {uptime}",
        "quit": "Salir",
        "starting": "Iniciando...",
        "stopping": "Deteniendo...",
        "settings": "⚙️ Configuración",
        "website": "🌐 server-nexe.com",
        "donate": "💚 Apoyar el proyecto",
        "uninstall": "🗑 Desinstalar Nexe",
        "uninstall_title": "Desinstalar Nexe",
        "uninstall_warning": "Esto borrará TODA la instalación de Nexe:\n\n• Modelos descargados\n• Memoria y conversaciones\n• Base de conocimiento\n• Configuración\n\n{storage}\n\nEsta acción NO se puede deshacer.",
        "uninstall_confirm": "Estás a punto de borrar Nexe y todos sus datos permanentemente.",
        "uninstall_checkbox": "Confirmo que quiero borrarlo todo",
        "uninstall_done": "Nexe se ha desinstalado correctamente.\n\n{details}",
        "uninstall_partial": "Nexe se ha detenido, pero no se pudo borrar por completo.\n\n{details}\n\nBorra manualmente lo que quede.",
        "uninstall_storage": "Espacio que se liberará: {size}",
        "uninstall_removed": "Borrado:",
        "uninstall_failed": "No se pudo borrar:",
        "uninstall_data_title": "Datos de Nexe",
        "uninstall_data_message": "¿Quieres conservar tus datos?\n\n• Conversaciones y memoria\n• Base de conocimiento\n• Configuración\n\nSe guardarán en ~/nexe-backup-[fecha]",
        "uninstall_keep_data": "Sí, conservar datos",
        "uninstall_delete_all": "No, borrar todo",
        "uninstall_backup_ok": "Datos guardados en {path}",
        "uninstall_backup_failed": "No se pudieron guardar los datos",
    },
    "en": {
        "start": "▶ Start Server",
        "stop": "⏹ Stop Server",
        "status_running": "Server running",
        "status_stopped": "Server stopped",
        "open_ui": "🌐 Open Web UI",
        "open_logs": "📄 Open logs",
        "docs": "📖 Documentation",
        "ram": "🧠 RAM: {ram}",
        "uptime": "⏱ Uptime: {uptime}",
        "quit": "Quit",
        "starting": "Starting...",
        "stopping": "Stopping...",
        "settings": "⚙️ Settings",
        "website": "🌐 server-nexe.com",
        "donate": "💚 Support the project",
        "uninstall": "🗑 Uninstall Nexe",
        "uninstall_title": "Uninstall Nexe",
        "uninstall_warning": "This will DELETE the entire Nexe installation:\n\n• Downloaded models\n• Memory and conversations\n• Knowledge base data\n• Configuration\n\n{storage}\n\nThis action CANNOT be undone.",
        "uninstall_confirm": "You are about to permanently delete Nexe and all its data.",
        "uninstall_checkbox": "I confirm I want to delete everything",
        "uninstall_done": "Nexe has been uninstalled successfully.\n\n{details}",
        "uninstall_partial": "Nexe has been stopped, but could not be fully deleted.\n\n{details}\n\nManually delete what remains.",
        "uninstall_storage": "Space to be freed: {size}",
        "uninstall_removed": "Removed:",
        "uninstall_failed": "Could not remove:",
        "uninstall_data_title": "Nexe Data",
        "uninstall_data_message": "Do you want to keep your data?\n\n• Conversations and memory\n• Knowledge base\n• Configuration\n\nIt will be saved to ~/nexe-backup-[date]",
        "uninstall_keep_data": "Yes, keep data",
        "uninstall_delete_all": "No, delete all",
        "uninstall_backup_ok": "Data saved to {path}",
        "uninstall_backup_failed": "Could not save data",
    },
}


def _detect_lang():
    """Detect language from env or .env file."""
    lang = os.environ.get("NEXE_LANG", "")
    if lang in ("ca", "es", "en"):
        return lang
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("NEXE_LANG="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val in ("ca", "es", "en"):
                    return val
    return "ca"
