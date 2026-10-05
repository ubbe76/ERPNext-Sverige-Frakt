"""Testhjälpare för frakt."""

from unittest.mock import patch

import frappe
from erpnext_sverige.setup.company import TAX_CATEGORY_SE
from erpnext_sverige.tests.utils import COMPANY, account, ensure_test_company, make_party

from erpnext_sverige_frakt.frakt.artikel import FRAKTARTIKEL, sakerstall_fraktartikel

SAVEPOINT = "frakt_test_commit"


def commit_som_savepoint(testfall):
	"""Låt `frappe.db.commit` sätta en savepoint i stället för att committa, under ett test.

	Bokningskoden committar medvetet (bokningen finns redan hos Sendify) och rullar tillbaka vid fel.
	I tester skulle det spara allt som testklassen skapat på test-siten, eftersom Frappe bara rullar
	tillbaka när klassen är klar. Här rullar `rollback()` tillbaka till senaste "commit", precis som
	i drift, och IntegrationTestCase rullar tillbaka allt när klassen är klar.
	"""
	db = frappe.db
	rollback = db.rollback

	def commit(*, chain=False):
		db.value_cache.clear()
		db.savepoint(SAVEPOINT)

	def rollback_till_savepoint(*, save_point=None, chain=False):
		rollback(save_point=save_point or SAVEPOINT)

	db.savepoint(SAVEPOINT)
	for namn, ersattning in (("commit", commit), ("rollback", rollback_till_savepoint)):
		p = patch.object(db, namn, ersattning)
		p.start()
		testfall.addCleanup(p.stop)


def make_eur_pall(name="_Test EUR-pall", egenvikt=25):
	if not frappe.db.exists("Forpackningstyp", name):
		frappe.get_doc(
			{
				"doctype": "Forpackningstyp",
				"forpackningstyp_namn": name,
				"kollityp": "Pall",
				"langd_cm": 120,
				"bredd_cm": 80,
				"hojd_cm": 150,
				"egenvikt_kg": egenvikt,
				"stapelbar": 0,
				"flakmeter": 0.4,
			}
		).insert()
	return name


def make_frakt_item(item_code, weight_uom="Kg", uoms=None, **fields):
	"""Skapar eller uppdaterar en artikel med fraktfält. uoms: [(uom, conversion_factor)]."""
	doc = frappe.get_doc("Item", item_code) if frappe.db.exists("Item", item_code) else frappe.new_doc("Item")
	doc.update(
		{
			"item_code": item_code,
			"item_name": item_code,
			"item_group": "Services",
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"weight_uom": weight_uom,
			**fields,
		}
	)
	if uoms:
		doc.uoms = []
		doc.append("uoms", {"uom": "Nos", "conversion_factor": 1})
		for uom, factor in uoms:
			doc.append("uoms", {"uom": uom, "conversion_factor": factor})
	doc.save()
	return doc.name


def make_adress(titel, lank_doctype, lank_namn, foretag=False, land="Sweden"):
	namn = frappe.db.get_value("Address", {"address_title": titel})
	if namn:
		return namn
	return (
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": titel,
				"address_type": "Shipping" if not foretag else "Billing",
				"address_line1": "Testgatan 1",
				"city": "Göteborg",
				"pincode": "41107",
				"country": land,
				"is_your_company_address": int(foretag),
				"links": [{"link_doctype": lank_doctype, "link_name": lank_namn}],
			}
		)
		.insert()
		.name
	)


def make_kontakt(fornamn, lank_doctype, lank_namn, epost="test@example.com", telefon="0701234567"):
	namn = frappe.db.get_value("Contact", {"first_name": fornamn})
	if namn:
		return namn
	kontakt = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": fornamn,
			"links": [{"link_doctype": lank_doctype, "link_name": lank_namn}],
		}
	)
	if epost:
		kontakt.append("email_ids", {"email_id": epost, "is_primary": 1})
	if telefon:
		kontakt.append("phone_nos", {"phone": telefon, "is_primary_mobile_no": 1})
	return kontakt.insert().name


def make_kund_med_adress(namn="_Test Fraktkund"):
	make_party("Customer", namn, TAX_CATEGORY_SE)
	make_adress(f"{namn} leverans", "Customer", namn)
	make_kontakt(f"{namn} kontakt", "Customer", namn)
	return namn


def aktivera_frakt(**andringar):
	ensure_test_company()
	sakerstall_fraktartikel()
	inst = frappe.get_doc("Fraktinstallningar")
	inst.update(
		{
			"aktiverad": 1,
			"leverantor": "Sendify",
			"miljo": "Sandlåda",
			"api_nyckel": "test-nyckel",
			"bolag": COMPANY,
			"avsandaradress": make_adress("_Test Svenska AB lager", "Company", COMPANY, foretag=True),
			"avsandarkontakt": make_kontakt("_Test Lagerchef", "Company", COMPANY),
			"upphamtningstider": [
				{"veckodag": dag, "fran": "09:00:00", "till": "16:00:00"}
				for dag in ("Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag")
			],
			"paslag_procent": 10,
			"paslag_belopp": 20,
			"fraktartikel": FRAKTARTIKEL,
			"prisandring_grans_procent": 5,
			**andringar,
		}
	)
	inst.save()
	frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
	return inst


def make_foljesedel(kund, rader, po_no=None):
	"""rader: [(item_code, qty)] eller [(item_code, qty, uom)]. Returnerar en godkänd följesedel."""
	dn = frappe.get_doc(
		{
			"doctype": "Delivery Note",
			"company": COMPANY,
			"customer": kund,
			"po_no": po_no,
			"shipping_address_name": frappe.db.get_value("Address", {"address_title": f"{kund} leverans"}),
			"contact_person": frappe.db.get_value("Contact", {"first_name": f"{kund} kontakt"}),
			"items": [
				{"item_code": r[0], "qty": r[1], "rate": 100, **({"uom": r[2]} if len(r) > 2 else {})}
				for r in rader
			],
		}
	)
	dn.insert()
	dn.submit()
	return dn
