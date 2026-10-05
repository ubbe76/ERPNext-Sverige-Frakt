"""Avsändare och mottagare i fraktmodulens part-format, från ERPNext:s Address och Contact."""

from datetime import date, datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, get_time, getdate, today


def part(namn, adress, kontakt, privatperson=False) -> dict:
	a = (
		frappe.db.get_value(
			"Address", adress, ["address_line1", "address_line2", "pincode", "city", "country"], as_dict=True
		)
		if adress
		else frappe._dict()
	)
	k = (
		frappe.db.get_value(
			"Contact", kontakt, ["first_name", "last_name", "mobile_no", "phone", "email_id"], as_dict=True
		)
		if kontakt
		else frappe._dict()
	)
	landskod = frappe.db.get_value("Country", a.country, "code") if a.country else None
	return {
		"namn": namn,
		"adressrad_1": a.address_line1,
		"adressrad_2": a.address_line2,
		"postnummer": a.pincode,
		"ort": a.city,
		"landskod": landskod.upper() if landskod else None,
		"kontakt_namn": " ".join(filter(None, [k.first_name, k.last_name])) or None,
		"telefon": k.mobile_no or k.phone,
		"epost": k.email_id,
		"privatperson": bool(privatperson),
	}


def kontaktens_telefon(kontakt) -> str | None:
	if not kontakt:
		return None
	mobil, telefon = frappe.db.get_value("Contact", kontakt, ["mobile_no", "phone"]) or (None, None)
	return mobil or telefon


def avsandare(inst) -> dict:
	namn = frappe.db.get_value("Company", inst.bolag, "company_name")
	avs = part(namn, inst.avsandaradress, inst.avsandarkontakt)
	avs["telefon"] = inst.get("avsandartelefon") or avs["telefon"]
	return avs


def kontrollera_telefon(sandning) -> None:
	"""Transportören kräver telefonnummer; säg var det fylls i innan något skickas."""
	if not sandning["avsandare"].get("telefon"):
		frappe.throw(_("Avsändarens telefon saknas. Fyll i Telefon i Fraktinställningar."))
	if not sandning["mottagare"].get("telefon"):
		frappe.throw(_("Mottagarens telefon saknas. Fyll i fältet Mottagarens telefon på försändelsen."))


VECKODAGAR = ("Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag")
SOK_DAGAR = 31  # så långt framåt nästa upphämtningsdag letas


def _helglista(bolag: str, datum: date) -> str | None:
	"""Helglistan som gäller bolaget på datumet: tilldelningen för datumet (HRMS), annars bolagets standardlista."""
	if frappe.db.exists("DocType", "Holiday List Assignment"):
		lista = frappe.db.get_value(
			"Holiday List Assignment",
			{"applicable_for": "Company", "assigned_to": bolag, "from_date": ("<=", datum), "docstatus": 1},
			"holiday_list",
			order_by="from_date desc",
		)
		if lista:
			return lista
	return frappe.db.get_value("Company", bolag, "default_holiday_list")


def ar_rod_dag(bolag: str | None, datum) -> bool:
	"""Röd dag i bolagets helglista. Vanliga veckohelger räknas inte: de styrs av upphämtningstiderna."""
	if not bolag:
		return False
	datum = getdate(datum)
	lista = _helglista(bolag, datum)
	return bool(
		lista and frappe.db.exists("Holiday", {"parent": lista, "holiday_date": datum, "weekly_off": 0})
	)


def upphamtningstider(inst, datum) -> tuple[time, time] | None:
	"""Upphämtningens från- och till-tid den dagen, eller None om det inte finns någon upphämtning."""
	datum = getdate(datum)
	rad = next((r for r in inst.upphamtningstider if r.veckodag == VECKODAGAR[datum.weekday()]), None)
	if not rad or ar_rod_dag(inst.bolag, datum):
		return None
	return get_time(rad.fran), get_time(rad.till)


def forsta_upphamtningsdag(inst, fran_och_med) -> date:
	"""Första dagen med upphämtning från och med datumet."""
	dag = getdate(fran_och_med)
	for _i in range(SOK_DAGAR):
		if upphamtningstider(inst, dag):
			return dag
		dag += timedelta(days=1)
	frappe.throw(
		_(
			"Ingen upphämtning de närmaste {0} dagarna. Kontrollera Upphämtningstider i Fraktinställningar."
		).format(SOK_DAGAR)
	)


def nasta_upphamtningsdag(inst, fran: date | None = None) -> date:
	"""Första dagen med upphämtning efter i dag (eller efter datumet)."""
	return forsta_upphamtningsdag(inst, getdate(fran or today()) + timedelta(days=1))


def forsta_upphamtning(inst, fran_och_med=None) -> datetime:
	"""Datum och starttid för första upphämtningen från och med datumet (annars nästa upphämtningsdag)."""
	dag = forsta_upphamtningsdag(inst, fran_och_med) if fran_och_med else nasta_upphamtningsdag(inst)
	return upphamtningstid(dag, upphamtningstider(inst, dag)[0])


def kontrollera_upphamtningsdag(inst, datum) -> None:
	if not upphamtningstider(inst, datum):
		datum = getdate(datum)
		frappe.throw(
			_("Ingen upphämtning {0} ({1}). Välj en annan upphämtningsdag; nästa är {2}.").format(
				frappe.format(datum, "Date"),
				_(VECKODAGAR[datum.weekday()]).lower(),
				frappe.format(forsta_upphamtningsdag(inst, datum), "Date"),
			)
		)


@frappe.whitelist()
def hamta_upphamtningstider(datum: str) -> dict:
	"""Tiderna för upphämtningsdagen i Shipment-formuläret."""
	from erpnext_sverige_frakt.frakt import hamta_installningar

	frappe.has_permission("Shipment", "read", throw=True)
	inst = hamta_installningar()
	if tider := upphamtningstider(inst, datum):
		return {"fran": str(tider[0]), "till": str(tider[1])}
	try:
		kontrollera_upphamtningsdag(inst, datum)
	except frappe.ValidationError as fel:
		frappe.clear_last_message()
		return {"stangt": str(fel)}


def upphamtningstid(datum, tid) -> datetime:
	return get_datetime(f"{getdate(datum)} {get_time(tid)}")
