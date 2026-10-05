"""Fraktpris till kund (påslag), register över transportörsprodukter, prisförfrågan och fraktrad på faktura."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, rounded

from erpnext_sverige_frakt.frakt import FraktFel, hamta_installningar, leverantor, visa_fraktfel
from erpnext_sverige_frakt.frakt.kollin import foresla_kollin
from erpnext_sverige_frakt.frakt.parter import avsandare, forsta_upphamtning, nasta_upphamtningsdag, part


def kundpris(pris: float) -> float:
	inst = hamta_installningar()
	return rounded(flt(pris) * (1 + flt(inst.paslag_procent) / 100) + flt(inst.paslag_belopp), 0)


def registrera_produkter(priser: list[dict]) -> list[dict]:
	"""Skapar saknade Fraktprodukter och sätter "fraktprodukt" och "kundpris" på varje pris."""
	for p in priser:
		namn = f"{p['transportor']} – {p['produkt']}"
		if not frappe.db.exists("Fraktprodukt", namn):
			frappe.get_doc(
				{
					"doctype": "Fraktprodukt",
					"leverantor": hamta_installningar().leverantor,
					"transportorskod": p.get("transportorskod"),
					"transportor": p["transportor"],
					"produkt": p["produkt"],
				}
			).insert(ignore_permissions=True)
		p["fraktprodukt"] = namn
		p["kundpris"] = kundpris(p["pris"])
	return sorted(priser, key=lambda p: p["pris"])


def lagg_frakt_pa_faktura(doc, method=None):
	"""Sales Invoice.before_insert: fraktartikel per bokad Shipment på fakturans följesedlar, en gång per Shipment."""
	inst = frappe.get_cached_doc("Fraktinstallningar")
	if not (inst.aktiverad and inst.fraktartikel and doc.company == inst.bolag):
		return
	if any(r.item_code == inst.fraktartikel for r in doc.items):
		return
	foljesedlar = list({r.delivery_note for r in doc.items if r.delivery_note})
	if not foljesedlar:
		return
	if _frakt_redan_pa_foljesedlar(foljesedlar, inst.fraktartikel):
		return
	shipments = frappe.get_all(
		"Shipment Delivery Note",
		filters={"delivery_note": ["in", foljesedlar], "parenttype": "Shipment"},
		pluck="parent",
		distinct=True,
	)
	for s in frappe.get_all(
		"Shipment",
		filters={"name": ["in", shipments], "docstatus": 1, "status": ["in", ["Booked", "Completed"]]},
		fields=["name", "kundpris", "carrier", "carrier_service"],
		order_by="name",
	):
		if not flt(s.kundpris) or _redan_fakturerad(s.name):
			continue
		doc.append(
			"items",
			{
				"item_code": inst.fraktartikel,
				"qty": 1,
				"rate": flt(s.kundpris),
				"description": _("Frakt {0} {1}").format(s.carrier, s.carrier_service),
				"frakt_shipment": s.name,
			},
		)
		_fyll_i_artikelrad(doc, doc.items[-1])


def _frakt_redan_pa_foljesedlar(foljesedlar, fraktartikel) -> bool:
	"""Frakt som redan följer med följesedlarna (från ordern) faktureras därifrån, inte av hooken."""
	if frappe.db.exists(
		"Delivery Note Item",
		{"parent": ["in", foljesedlar], "item_code": fraktartikel, "docstatus": ["<", 2]},
	):
		return True
	if frappe.db.exists(
		"Sales Invoice Item",
		{"delivery_note": ["in", foljesedlar], "item_code": fraktartikel, "docstatus": ["<", 2]},
	):
		return True
	ordrar = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": ["in", foljesedlar], "against_sales_order": ["is", "set"]},
		pluck="against_sales_order",
		distinct=True,
	)
	return bool(
		ordrar
		and frappe.db.exists(
			"Sales Order Item", {"parent": ["in", ordrar], "item_code": fraktartikel, "docstatus": ["<", 2]}
		)
	)


def _fyll_i_artikelrad(doc, rad) -> None:
	"""before_insert körs efter mappningen, så uom, konto m.m. på den tillagda raden fylls i här."""
	beskrivning, kurs = rad.description, rad.rate
	doc.set_missing_item_details(for_validate=True)
	rad.description, rad.rate = beskrivning, kurs


def _redan_fakturerad(shipment) -> bool:
	return bool(frappe.db.exists("Sales Invoice Item", {"frakt_shipment": shipment, "docstatus": ["<", 2]}))


FORSALJNING = ("Quotation", "Sales Order")


def priser_for_tillfallig_sandning(sandning, upphamtning) -> dict:
	"""Skapar en sändning hos leverantören, hämtar priser och raderar sändningen igen."""
	lev = leverantor()
	sendify_id = lev.skapa_sandning(sandning)
	try:
		priser, varningar = lev.hamta_priser(sendify_id, upphamtning)
	finally:
		try:
			lev.radera_sandning(sendify_id)
		except FraktFel:
			frappe.log_error(title="Sendify: kunde inte radera tillfällig sändning", message=sendify_id)
	return {"priser": registrera_produkter(priser), "varningar": varningar}


@frappe.whitelist()
@visa_fraktfel
def kontrollera(doctype: str, name: str) -> dict:
	if doctype not in FORSALJNING:
		frappe.throw(_("Fraktpris kan bara kontrolleras på offert och försäljningsorder"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	inst = hamta_installningar()
	kollin, varningar = foresla_kollin(
		[(r.item_code, r.stock_qty) for r in doc.items if r.item_code != inst.fraktartikel]
	)
	if not kollin:
		frappe.throw(_("Inga kollin kunde föreslås: {0}").format(", ".join(varningar)))
	kund = (
		doc.customer
		if doctype == "Sales Order"
		else (doc.party_name if doc.quotation_to == "Customer" else None)
	)
	privat = bool(kund) and frappe.db.get_value("Customer", kund, "customer_type") == "Individual"
	sandning = {
		"avsandare": avsandare(inst),
		"mottagare": part(
			doc.customer_name, doc.shipping_address_name or doc.customer_address, doc.contact_person, privat
		),
		"kollin": kollin,
		"referens_id": f"{doctype} {name}",
	}
	# Upphämtning tidigast nästa upphämtningsdag, och inte före leveransdatumet
	datum = nasta_upphamtningsdag(inst)
	if doc.get("delivery_date"):
		datum = max(getdate(doc.delivery_date), datum)
	svar = priser_for_tillfallig_sandning(sandning, forsta_upphamtning(inst, datum))
	svar["varningar"] = varningar + svar["varningar"]
	for p in svar["priser"]:
		p["forvald"] = p["fraktprodukt"] == doc.get("fraktprodukt")
	return svar


@frappe.whitelist()
def lagg_till_frakt(doctype: str, name: str, fraktprodukt: str, kundpris: float) -> None:
	if doctype not in FORSALJNING:
		frappe.throw(_("Frakt kan bara läggas till på offert och försäljningsorder"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Frakt kan bara läggas till på ett utkast. Använd Spara val på godkända dokument."))
	inst = hamta_installningar()
	produkt = frappe.get_doc("Fraktprodukt", fraktprodukt)
	beskrivning = _("Frakt {0} {1}").format(produkt.transportor, produkt.produkt)
	rad = next((r for r in doc.items if r.item_code == inst.fraktartikel), None)
	if rad:
		rad.update({"rate": flt(kundpris), "description": beskrivning})
	else:
		rad = doc.append(
			"items",
			{"item_code": inst.fraktartikel, "qty": 1, "rate": flt(kundpris), "description": beskrivning},
		)
		if doctype == "Sales Order":
			rad.delivery_date = doc.delivery_date or doc.items[0].delivery_date
	doc.fraktprodukt = fraktprodukt
	doc.save()


@frappe.whitelist()
def spara_val_order(doctype: str, name: str, fraktprodukt: str) -> None:
	if doctype not in FORSALJNING:
		frappe.throw(_("Fel dokumenttyp"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	doc.db_set("fraktprodukt", fraktprodukt)
