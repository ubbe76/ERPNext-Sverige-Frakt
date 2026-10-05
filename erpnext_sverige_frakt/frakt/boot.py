import frappe


def extend_bootinfo(bootinfo):
	bootinfo.frakt_aktiverad = bool(frappe.db.get_single_value("Fraktinstallningar", "aktiverad"))
