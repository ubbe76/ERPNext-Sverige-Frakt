"""Transportbokning på Shipment: skapa från följesedel, priser, spara val, boka, dokument och avbokning."""

import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import make_shipment
from frappe import _
from frappe.contacts.doctype.address.address import get_address_display
from frappe.utils import cint, flt, now_datetime

from erpnext_sverige_frakt.frakt import FraktFel, hamta_installningar, leverantor, visa_fraktfel
from erpnext_sverige_frakt.frakt.fraktpris import kundpris, registrera_produkter
from erpnext_sverige_frakt.frakt.kollin import foresla_kollin
from erpnext_sverige_frakt.frakt.parter import (
	avsandare,
	kontaktens_telefon,
	kontrollera_telefon,
	kontrollera_upphamtningsdag,
	nasta_upphamtningsdag,
	part,
	upphamtningstid,
	upphamtningstider,
)


def _foljesedlar(doc) -> list[str]:
	return [r.delivery_note for r in doc.shipment_delivery_note if r.delivery_note]


def _lagerrader(foljesedlar) -> list[tuple[str, float]]:
	filters = {"parent": ["in", foljesedlar], "parenttype": "Delivery Note"}
	fraktartikel = frappe.db.get_single_value("Fraktinstallningar", "fraktartikel")
	if fraktartikel:
		filters["item_code"] = ["!=", fraktartikel]
	return frappe.get_all(
		"Delivery Note Item", filters=filters, fields=["item_code", "stock_qty"], as_list=True
	)


def satt_kollin(doc, kollin) -> None:
	doc.shipment_parcel = []
	for k in kollin:
		doc.append(
			"shipment_parcel",
			{
				"length": k["langd_cm"],
				"width": k["bredd_cm"],
				"height": k["hojd_cm"],
				"weight": k["vikt_kg"],
				"count": k["antal"],
				"kollityp": k["kollityp"],
				"stapelbar": k["stapelbar"],
				"flakmeter": k["flakmeter"],
				"beskrivning": k["beskrivning"],
			},
		)


def _kontrollera_vikter(kollin, varningar) -> None:
	"""ERPNext vägrar kolli utan vikt med ett generellt fel; visa i stället våra varningar."""
	if any(flt(k["vikt_kg"]) <= 0 for k in kollin):
		frappe.throw(
			_("Kolliförslaget kan inte skapas:<br>")
			+ "<br>".join(frappe.utils.escape_html(v) for v in varningar)
		)


def _visa_varningar(varningar):
	if varningar:
		frappe.msgprint("<br>".join(varningar), title=_("Kontrollera kollina"), indicator="orange")


def _forvald_fraktprodukt(dn) -> str | None:
	order = next((r.against_sales_order for r in dn.items if r.against_sales_order), None)
	if order and (produkt := frappe.db.get_value("Sales Order", order, "fraktprodukt")):
		return produkt
	return frappe.db.get_value("Customer", dn.customer, "forvald_fraktprodukt")


@frappe.whitelist()
def skapa_shipment(delivery_note: str) -> str:
	inst = hamta_installningar()
	dn = frappe.get_doc("Delivery Note", delivery_note)
	dn.check_permission("read")
	frappe.has_permission("Shipment", "create", throw=True)

	doc = make_shipment(delivery_note)
	doc.shipment_delivery_note = []
	doc.append("shipment_delivery_note", {"delivery_note": dn.name, "grand_total": dn.grand_total})
	doc.pickup_from_type = "Company"
	doc.pickup_company = inst.bolag
	doc.pickup_address_name = inst.avsandaradress
	doc.pickup_address = get_address_display(inst.avsandaradress)
	doc.pickup_date = nasta_upphamtningsdag(inst)
	doc.pickup_from, doc.pickup_to = upphamtningstider(inst, doc.pickup_date)
	doc.description_of_content = _("Gods enligt följesedel {0}").format(dn.name)
	doc.avsandarens_referens = dn.name
	doc.mottagarens_referens = dn.po_no
	doc.fraktprodukt = _forvald_fraktprodukt(dn)
	doc.mottagartelefon = kontaktens_telefon(doc.delivery_contact_name)

	kollin, varningar = foresla_kollin(_lagerrader([dn.name]))
	_kontrollera_vikter(kollin, varningar)
	satt_kollin(doc, kollin)
	doc.insert()
	_visa_varningar(varningar)
	return doc.name


def _utkast(shipment: str):
	doc = frappe.get_doc("Shipment", shipment)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Försändelsen {0} är redan bokad eller avbruten").format(doc.name))
	return doc


@frappe.whitelist()
def foresla_kollin_igen(shipment: str) -> list[str]:
	doc = _utkast(shipment)
	kollin, varningar = foresla_kollin(_lagerrader(_foljesedlar(doc)))
	_kontrollera_vikter(kollin, varningar)
	satt_kollin(doc, kollin)
	doc.save()
	return varningar


def sandning_fran_shipment(doc) -> dict:
	kund = frappe.db.get_value(
		"Customer", doc.delivery_customer, ["customer_name", "customer_type"], as_dict=True
	)
	mottagare = part(
		kund.customer_name,
		doc.delivery_address_name,
		doc.delivery_contact_name,
		privatperson=kund.customer_type == "Individual",
	)
	mottagare["telefon"] = doc.get("mottagartelefon") or mottagare["telefon"]
	return {
		"avsandare": avsandare(hamta_installningar()),
		"mottagare": mottagare,
		"kollin": [
			{
				"kollityp": r.kollityp or "Paket",
				"langd_cm": r.length,
				"bredd_cm": r.width,
				"hojd_cm": r.height,
				"vikt_kg": r.weight,
				"antal": r.count,
				"stapelbar": r.stapelbar,
				"flakmeter": r.flakmeter,
				"beskrivning": r.beskrivning or doc.description_of_content,
			}
			for r in doc.shipment_parcel
		],
		"referens_id": doc.name,
		"avsandarens_referens": doc.avsandarens_referens,
		"mottagarens_referens": doc.mottagarens_referens,
	}


def _synka_sandning(doc) -> str:
	"""Skapar eller uppdaterar sändningen hos leverantören och returnerar dess id."""
	lev = leverantor()
	sandning = sandning_fran_shipment(doc)
	kontrollera_telefon(sandning)
	if doc.sendify_id:
		lev.uppdatera_sandning(doc.sendify_id, sandning)
	else:
		doc.db_set("sendify_id", lev.skapa_sandning(sandning), update_modified=False)
		frappe.db.commit()  # sändningen finns nu hos Sendify; spara id:t även om prisanropet misslyckas
	return doc.sendify_id


@frappe.whitelist()
@visa_fraktfel
def hamta_priser(shipment: str) -> dict:
	doc = _utkast(shipment)
	kontrollera_upphamtningsdag(hamta_installningar(), doc.pickup_date)
	sendify_id = _synka_sandning(doc)
	priser, varningar = leverantor().hamta_priser(
		sendify_id, upphamtningstid(doc.pickup_date, doc.pickup_from)
	)
	priser = registrera_produkter(priser)
	for p in priser:
		p["forvald"] = p["fraktprodukt"] == doc.fraktprodukt
	return {"priser": priser, "varningar": varningar}


@frappe.whitelist()
def spara_val(shipment: str, fraktprodukt: str, pris: float, valuta: str = "SEK") -> None:
	doc = _utkast(shipment)
	doc.update(
		{
			"fraktprodukt": fraktprodukt,
			"fraktpris": flt(pris),
			"fraktpris_valuta": valuta,
			"kundpris": kundpris(pris),
			"pris_hamtat": now_datetime(),
		}
	)
	doc.save()


DOKUMENT = {"waybill": "Fraktsedel", "label": "Etikett"}


@frappe.whitelist()
@visa_fraktfel
def boka(shipment: str, token: str, fraktprodukt: str, pris: float, valuta: str = "SEK") -> None:
	doc = _utkast(shipment)
	if not doc.sendify_id:
		frappe.throw(_("Hämta priser innan du bokar"))
	kontrollera_upphamtningsdag(hamta_installningar(), doc.pickup_date)
	# Kontrollera det ERPNext kräver vid godkännandet innan betald bokning görs hos Sendify
	doc.check_permission("submit")
	if flt(doc.value_of_goods) <= 0:
		frappe.throw(_("Godsvärdet måste vara större än noll innan försändelsen kan bokas"))
	if not doc.shipment_parcel:
		frappe.throw(_("Försändelsen saknar kollin"))
	resultat = leverantor().boka(token)
	_spara_bokning(doc, fraktprodukt, flt(pris), valuta, resultat)


def _spara_bokning(doc, fraktprodukt, pris, valuta, resultat):
	try:
		_spara_lokalt(doc, fraktprodukt, pris, valuta, resultat)
	except Exception:
		# Bokningen finns redan hos Sendify – spårningsnumret får inte gå förlorat
		frappe.db.rollback()
		nummer = resultat["sparningsnummer"]
		frappe.log_error(
			title=f"Sendify: bokning {doc.name} kunde inte sparas",
			message=f"Sendify-id: {doc.sendify_id}\nSpårningsnummer: {nummer}\n\n{frappe.get_traceback()}",
		)
		frappe.db.commit()
		frappe.throw(
			_(
				"Försändelsen bokades hos Sendify med spårningsnummer {0}, men kunde inte sparas i ERPNext. "
				"Kontakta support eller avboka den hos Sendify."
			).format(nummer)
		)

	try:
		_hamta_dokument(doc)
	except Exception as fel:
		frappe.db.rollback()
		frappe.log_error(title=f"Sendify: fraktsedel för {doc.name} kunde inte hämtas")
		frappe.db.commit()
		frappe.msgprint(
			_(
				"Bokningen är klar, men fraktsedeln kunde inte hämtas: {0}. Använd knappen Hämta fraktsedel."
			).format(getattr(fel, "meddelande", None) or fel),
			indicator="orange",
		)
	try:
		from erpnext_sverige_frakt.frakt.sparning import uppdatera_shipment

		uppdatera_shipment(doc)
	except ImportError:
		pass  # spårningen hämtas av schemaläggaren
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Sendify: spårning för {doc.name} kunde inte hämtas")
		frappe.db.commit()


def _spara_lokalt(doc, fraktprodukt, pris, valuta, resultat):
	produkt = frappe.get_doc("Fraktprodukt", fraktprodukt)
	# Behåll bara ett kundpris som användaren ändrat; ett automatiskt beräknat räknas om efter prisändring
	andrat_av_anvandare = bool(
		doc.kundpris and doc.fraktprodukt == fraktprodukt and flt(doc.kundpris) != kundpris(doc.fraktpris)
	)
	if not andrat_av_anvandare:
		doc.kundpris = kundpris(pris)
	doc.update(
		{
			"fraktprodukt": fraktprodukt,
			"fraktpris": pris,
			"fraktpris_valuta": valuta,
			"shipment_amount": pris,
			"carrier": produkt.transportor,
			"carrier_service": produkt.produkt,
			"service_provider": produkt.leverantor,
			"shipment_id": doc.sendify_id,
			"awb_number": resultat["sparningsnummer"],
			"dokumenttyper": ",".join(resultat.get("dokumenttyper") or ["label"]),
		}
	)
	doc.submit()
	doc.db_set("status", "Booked")
	for dn in _foljesedlar(doc):
		frappe.db.set_value(
			"Delivery Note",
			dn,
			{
				"transporter_name": produkt.transportor,
				"lr_no": resultat["sparningsnummer"],
				"lr_date": doc.pickup_date,
			},
		)
	frappe.db.commit()  # bokningen är gjord hos leverantören – spara innan dokument och spårning hämtas


def _hamta_dokument(doc):
	typer = [t for t in DOKUMENT if t in (doc.dokumenttyper or "label").split(",")]
	for typ in typer:
		pdf = leverantor().hamta_dokument(doc.sendify_id, typ)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{DOKUMENT[typ]}-{doc.name}.pdf",
				"attached_to_doctype": "Shipment",
				"attached_to_name": doc.name,
				"is_private": 1,
				"content": pdf,
			}
		).insert(ignore_permissions=True)
	doc.db_set("etikett_hamtad", 1)


@frappe.whitelist()
@visa_fraktfel
def hamta_dokument(shipment: str) -> None:
	doc = frappe.get_doc("Shipment", shipment)
	doc.check_permission("write")
	if doc.status not in ("Booked", "Completed"):
		frappe.throw(_("Försändelsen är inte bokad"))
	_hamta_dokument(doc)


@frappe.whitelist()
def boka_vald_produkt(shipment: str, bekraftat: int = 0) -> dict:
	doc = _utkast(shipment)
	if not doc.fraktprodukt:
		frappe.throw(_("Välj en fraktprodukt först"))
	svar = hamta_priser(shipment)
	pris = next((p for p in svar["priser"] if p["fraktprodukt"] == doc.fraktprodukt), None)
	if not pris:
		return {"status": "saknas", **svar}
	if flt(doc.fraktpris) and not cint(bekraftat):
		andring = abs(pris["pris"] - flt(doc.fraktpris)) / flt(doc.fraktpris) * 100
		if andring > flt(hamta_installningar().prisandring_grans_procent):
			return {"status": "prisandring", "gammalt": flt(doc.fraktpris), "nytt": pris["pris"]}
	boka(shipment, pris["token"], pris["fraktprodukt"], pris["pris"], pris["valuta"])
	return {"status": "bokad"}


def _aktiverad() -> bool:
	return bool(frappe.db.get_single_value("Fraktinstallningar", "aktiverad"))


def avboka_vid_avbrott(doc, method=None):
	"""Shipment.before_cancel: avboka hos leverantören innan försändelsen avbryts i ERPNext."""
	if not (doc.sendify_id and doc.status == "Booked"):
		return
	if not _aktiverad():
		frappe.throw(_("Aktivera transportbokning i Fraktinställningar för att kunna avboka hos Sendify"))
	try:
		leverantor().avboka(doc.sendify_id)
	except FraktFel as fel:
		frappe.throw(fel.som_html(), title=_("Sendify kunde inte avboka"))
	for dn in _foljesedlar(doc):
		frappe.db.set_value("Delivery Note", dn, {"transporter_name": None, "lr_no": None, "lr_date": None})


def radera_vid_borttagning(doc, method=None):
	"""Shipment.on_trash: radera ett obokat utkast hos leverantören."""
	if not (doc.sendify_id and doc.docstatus == 0 and _aktiverad()):
		return
	try:
		leverantor().radera_sandning(doc.sendify_id)
	except FraktFel:
		frappe.log_error(title="Sendify: kunde inte radera sändning", message=doc.sendify_id)
