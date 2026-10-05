"""Flyttar Upphämtning från/till i Fraktinställningar till tabellen Upphämtningstider (måndag-fredag)."""

import frappe

VARDAGAR = ("Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag")


def execute():
	if frappe.get_all("Upphamtningstid", filters={"parent": "Fraktinstallningar"}, limit=1):
		return
	# De gamla fälten finns inte längre i doctypen; värdena ligger kvar i tabSingles
	gamla = dict(
		frappe.db.sql(
			"""select field, value from `tabSingles` where doctype = 'Fraktinstallningar'
			and field in ('upphamtning_fran', 'upphamtning_till')"""
		)
	)
	fran = gamla.get("upphamtning_fran") or "09:00:00"
	till = gamla.get("upphamtning_till") or "16:00:00"
	# Raderna skrivs direkt: att spara hela inställningen kunde stoppas av annat som är ofullständigt i den
	for idx, dag in enumerate(VARDAGAR, start=1):
		frappe.get_doc(
			{
				"doctype": "Upphamtningstid",
				"parent": "Fraktinstallningar",
				"parenttype": "Fraktinstallningar",
				"parentfield": "upphamtningstider",
				"idx": idx,
				"veckodag": dag,
				"fran": fran,
				"till": till,
			}
		).db_insert()
	frappe.db.delete(
		"Singles",
		{"doctype": "Fraktinstallningar", "field": ("in", ("upphamtning_fran", "upphamtning_till"))},
	)
