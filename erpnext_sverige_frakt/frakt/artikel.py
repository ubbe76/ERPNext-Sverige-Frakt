"""Fraktartikeln: icke-lagerförd vara som frakten faktureras som (moms och konto följer av vanlig artikellogik)."""

import frappe

FRAKTARTIKEL = "Frakt"
FRAKTKONTO = "3520"


def fraktartiklar() -> list[str]:
	"""Hooken erpnext_sverige_fraktartiklar: ERPNext Sverige bokför fraktartikeln på konto 3520."""
	artikel = frappe.db.get_single_value("Fraktinstallningar", "fraktartikel")
	return [artikel] if artikel else []


def sakerstall_fraktartikel() -> None:
	"""Skapar artikeln "Frakt" med intäktskonto 3520 per bolag och pekar ut den i Fraktinställningar.

	Idempotent: befintliga artiklar och ett redan valt värde i inställningarna lämnas orörda.
	"""
	from erpnext_sverige.setup.custom_fields import GOODS

	if not frappe.db.exists("Item", FRAKTARTIKEL):
		item_group = "Services" if frappe.db.exists("Item Group", "Services") else None
		item_group = item_group or frappe.db.get_value("Item Group", {"is_group": 0})
		if not item_group:
			frappe.log_error(
				title="Fraktartikel", message="Ingen artikelgrupp finns, artikeln Frakt skapades inte"
			)
			return
		enhet = _standardenhet()
		if not enhet:
			frappe.log_error(title="Fraktartikel", message="Ingen enhet finns, artikeln Frakt skapades inte")
			return
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": FRAKTARTIKEL,
				"item_name": "Frakt",
				"item_group": item_group,
				"stock_uom": enhet,
				"is_stock_item": 0,
				"is_sales_item": 1,
				"is_purchase_item": 0,
				"se_goods_or_service": GOODS,
			}
		).insert(ignore_permissions=True)

	item = frappe.get_doc("Item", FRAKTARTIKEL)
	andrad = False
	for company in frappe.get_all("Company", pluck="name"):
		konto = frappe.db.get_value(
			"Account", {"company": company, "account_number": FRAKTKONTO, "is_group": 0}
		)
		if not konto:
			continue
		# ERPNext lägger själv till en rad för standardbolaget (med standardlager men utan intäktskonto)
		rad = next((d for d in item.item_defaults if d.company == company), None)
		if not rad:
			item.append("item_defaults", {"company": company, "income_account": konto})
			andrad = True
		elif not rad.income_account:
			rad.income_account = konto
			andrad = True
	if andrad:
		item.save(ignore_permissions=True)

	if item.is_stock_item or item.se_goods_or_service != GOODS:
		frappe.log_error(
			title="Fraktartikel",
			message="Artikeln Frakt är lagerförd eller inte Vara och används inte som fraktartikel",
		)
		return

	if not frappe.db.get_single_value("Fraktinstallningar", "fraktartikel"):
		frappe.db.set_single_value("Fraktinstallningar", "fraktartikel", FRAKTARTIKEL)
		frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")


def _standardenhet() -> str | None:
	"""Lagerinställningarnas standardenhet; enheterna kan ha svenska namn ("Styck" i stället för "Nos")."""
	for enhet in (frappe.db.get_single_value("Stock Settings", "stock_uom"), "Nos"):
		if enhet and frappe.db.exists("UOM", enhet):
			return enhet
	return frappe.db.get_value("UOM", {"enabled": 1, "must_be_whole_number": 1})
