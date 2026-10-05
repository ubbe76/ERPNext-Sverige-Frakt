import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext_sverige_frakt.frakt.artikel import sakerstall_fraktartikel
from erpnext_sverige_frakt.frakt.custom_fields import get_custom_fields

APP = "erpnext_sverige_frakt"


def before_install():
	"""Siter där frakten låg i ERPNext Sverige (före 0.3.0) har kvar modulposten Frakt, menyn och ikonen.

	Modulposten tas bort, och installationen lägger till den igen för den här appen. Tabeller och data rörs
	inte. Måste köras innan ERPNext Sverige 0.3.0 migreras, annars tas fraktens doctyper bort som föräldralösa.
	"""
	app = frappe.db.get_value("Module Def", "Frakt", "app_name")
	if app and app != APP:
		frappe.db.delete("Module Def", "Frakt")
	# Menyn och ikonen följer med; annars tar migrate bort dem som föräldralösa för ERPNext Sverige
	for doctype in ("Desktop Icon", "Workspace Sidebar"):
		if frappe.db.get_value(doctype, "Frakt", "app") not in (None, APP):
			frappe.db.set_value(doctype, "Frakt", "app", APP, update_modified=False)


def after_install():
	"""Även after_migrate: fälten på Item, Shipment med flera och fraktartikeln. Kan köras om."""
	create_custom_fields(get_custom_fields(), update=True)
	sakerstall_fraktartikel()
