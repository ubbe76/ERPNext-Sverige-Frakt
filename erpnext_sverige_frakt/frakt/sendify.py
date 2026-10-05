"""Sendify-API (https://api.sendify.com/docs). Den enda modulen som känner till Sendify.

Tar och ger dict:ar i fraktmodulens eget format (se docs/superpowers/specs/2026-10-01-frakt-sendify-design.md).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe import _
from frappe.utils import flt, get_system_timezone

from erpnext_sverige_frakt.frakt import FraktFel, hamta_installningar

BAS_URL = {
	"Sandlåda": "https://app.dev.sendify.se/external/v1",
	"Produktion": "https://app.sendify.se/external/v1",
}
TIMEOUT = 30
KOLLITYP = {"Paket": "PACKAGE", "Pall": "PALLET", "Övrigt": "UNSPECIFIED"}
PART = {"from": "Avsändare", "to": "Mottagare"}
FALT = {
	"weight_kg": "vikt",
	"width_cm": "bredd",
	"height_cm": "höjd",
	"depth_cm": "längd",
	"quantity": "antal",
	"type": "kollityp",
	"loading_meters": "flakmeter",
	"address_line_1": "adress",
	"postal_code": "postnummer",
	"city": "ort",
	"country_code": "land",
	"name": "namn",
	"phone": "telefon",
	"email": "e-post",
}
EJ_SVARAR = "Sendify svarar inte, försök igen"
EJ_SVARAR_BOKNING = "Sendify svarade inte på bokningen. Bokningen kan ha genomförts – kontrollera i Sendify innan du försöker igen."
OVANTAT_SVAR = "Sendify gav ett oväntat svar"


# --- HTTP ---------------------------------------------------------------------------------------------


def _anrop(metod, sokvag, data=None, installningar=None, ej_svar=EJ_SVARAR):
	inst = installningar or hamta_installningar()
	try:
		svar = requests.request(
			metod,
			BAS_URL[inst.miljo] + sokvag,
			json=data,
			headers={"x-api-key": inst.get_password("api_nyckel"), "Accept": "application/json"},
			timeout=TIMEOUT,
		)
	except requests.RequestException:
		raise FraktFel(_(ej_svar)) from None
	request_id = svar.headers.get("X-Sendify-Request-ID")
	if svar.status_code >= 400:
		frappe.log_error(
			title=f"Sendify {metod} {sokvag}",
			message=f"HTTP {svar.status_code}\nX-Sendify-Request-ID: {request_id}\n{svar.text[:2000]}",
			defer_insert=True,  # en vanlig insert rullas tillbaka när frappe.throw avbryter anropet
		)
		if svar.status_code >= 500:
			raise FraktFel(_(EJ_SVARAR), request_id=request_id)
		raise _fel_fran_svar(svar, request_id)
	if svar.status_code == 204 or not svar.content:
		return None
	try:
		return svar.json()
	except ValueError:
		raise FraktFel(_(OVANTAT_SVAR), request_id=request_id) from None


def _dict_svar(data, request_id=None) -> dict:
	if not isinstance(data, dict):
		raise FraktFel(_(OVANTAT_SVAR), request_id=request_id)
	return data


def _fel_fran_svar(svar, request_id):
	try:
		data = svar.json() or {}
	except ValueError:
		data = {}
	if not isinstance(data, dict):
		data = {}
	falt_fel = []
	fel = data.get("errors") or {}
	if isinstance(fel, dict):
		for falt, meddelanden in fel.items():
			for meddelande in meddelanden if isinstance(meddelanden, list) else [meddelanden]:
				falt_fel.append(f"{faltnamn(str(falt))}: {meddelande}")
	else:
		for post in fel if isinstance(fel, list) else [fel]:
			if isinstance(post, dict):
				text = post.get("message") or post.get("error")
				if not text:
					continue
				falt = post.get("field")
				falt_fel.append(f"{faltnamn(str(falt))}: {text}" if falt else str(text))
			else:
				falt_fel.append(str(post))
	meddelande = data.get("message") or data.get("error")
	if not isinstance(meddelande, str):
		meddelande = None
	if not meddelande:
		meddelande = (
			_("Sendify kunde inte behandla sändningen")
			if falt_fel
			else _("Sendify avvisade anropet (HTTP {0})").format(svar.status_code)
		)
	return FraktFel(meddelande, falt_fel=falt_fel, request_id=request_id)


def faltnamn(falt: str) -> str:
	"""packages[0].weight_kg → "Kolli 1: vikt", to.contact.email → "Mottagare: e-post"."""
	sista = FALT.get(falt.rsplit(".", 1)[-1], falt.rsplit(".", 1)[-1])
	if m := re.match(r"packages\[(\d+)\]", falt):
		return _("Kolli {0}: {1}").format(int(m.group(1)) + 1, sista)
	if (forsta := falt.split(".", 1)[0]) in PART:
		return f"{_(PART[forsta])}: {sista}"
	return sista


# --- Format --------------------------------------------------------------------------------------------


def _utan_tomma(varde):
	if isinstance(varde, dict):
		return {k: _utan_tomma(v) for k, v in varde.items() if v not in (None, "", [], {})}
	if isinstance(varde, list):
		return [_utan_tomma(v) for v in varde]
	return varde


def _part(p):
	return {
		"name": p.get("namn"),
		"address": {
			"address_line_1": p.get("adressrad_1"),
			"address_line_2": p.get("adressrad_2"),
			"postal_code": p.get("postnummer"),
			"city": p.get("ort"),
			"country_code": p.get("landskod"),
		},
		"contact": {"name": p.get("kontakt_namn"), "phone": p.get("telefon"), "email": p.get("epost")},
	}


def _kolli(k):
	return {
		"depth_cm": flt(k["langd_cm"]),
		"width_cm": flt(k["bredd_cm"]),
		"height_cm": flt(k["hojd_cm"]),
		"weight_kg": flt(k["vikt_kg"]),
		"quantity": int(k["antal"]),
		"type": KOLLITYP.get(k.get("kollityp") or "Paket", "UNSPECIFIED"),
		"stackable": bool(k.get("stapelbar")),
		"description": k.get("beskrivning"),
		"loading_meters": flt(k.get("flakmeter")) or None,
	}


def till_sendify(sandning):
	data = {
		"enable_bookable_validation": True,
		"from": _part(sandning["avsandare"]),
		"to": _part(sandning["mottagare"]),
		"reference_id": sandning.get("referens_id"),
		"sender_reference": sandning.get("avsandarens_referens"),
		"receiver_reference": sandning.get("mottagarens_referens"),
		"packages": [_kolli(k) for k in sandning["kollin"]],
		"system": "ERPNext",
	}
	data = _utan_tomma(data)
	data["to"]["is_private_individual"] = bool(sandning["mottagare"].get("privatperson"))
	return data


def _iso(tid: datetime) -> str:
	return tid.replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()


def _tid(text: str) -> datetime:
	"""ISO 8601 från Sendify (kan ha nanosekunder och Z) → naiv tid i systemets tidszon."""
	text = re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00")
	return datetime.fromisoformat(text).astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def _pris(r):
	return {
		"token": r["booking_token"],
		"transportorskod": r.get("carrier_code"),
		"transportor": r["carrier_name"],
		"produkt": r["product_name"],
		"pris": flt(r["price"]),
		"valuta": r.get("currency") or "SEK",
		"dagar_min": r.get("transport_business_days_min"),
		"dagar_max": r.get("transport_business_days_max"),
		"upphamtning": r.get("pickup") or {},
		"leverans": r.get("estimated_delivery") or {},
		"giltig_till": r.get("expires_at"),
	}


# --- Funktioner -------------------------------------------------------------------------------------------


def skapa_sandning(sandning) -> str:
	data = _dict_svar(_anrop("POST", "/shipments", till_sendify(sandning)))
	if not data.get("id"):
		raise FraktFel(_(OVANTAT_SVAR))
	return data["id"]


def uppdatera_sandning(sendify_id, sandning) -> None:
	_anrop("PUT", f"/shipments/{sendify_id}", till_sendify(sandning))


def radera_sandning(sendify_id) -> None:
	_anrop("DELETE", f"/shipments/{sendify_id}")


def hamta_priser(sendify_id, upphamtning: datetime):
	data = _dict_svar(
		_anrop(
			"POST",
			"/shipments/rates",
			{"shipment_id": sendify_id, "requested_pickup_time": _iso(upphamtning)},
		)
	)
	varningar = [
		f"{w['carrier_name']}: {'; '.join(w.get('warnings') or [])}" for w in data.get("warnings") or []
	]
	return [_pris(r) for r in data.get("rates") or []], varningar


def boka(token) -> dict:
	data = _dict_svar(_anrop("POST", "/shipments/book", {"booking_token": token}, ej_svar=EJ_SVARAR_BOKNING))
	return {
		"sparningsnummer": data.get("main_tracking_id"),
		"dokumenttyper": data.get("available_document_types") or [],
	}


def hamta_dokument(sendify_id, typ) -> bytes:
	data = _dict_svar(
		_anrop(
			"POST",
			"/shipments/print",
			{
				"shipment_ids": [sendify_id],
				"document_type": typ,
				"label_layout": "a4",
				"output_format": "url",
			},
		)
	)
	if not data.get("output_url"):
		raise FraktFel(_(OVANTAT_SVAR))
	try:
		pdf = requests.get(data["output_url"], timeout=TIMEOUT)
	except requests.RequestException:
		raise FraktFel(_(EJ_SVARAR)) from None
	if pdf.status_code >= 400:
		raise FraktFel(_("Dokumentet kunde inte hämtas från Sendify (HTTP {0})").format(pdf.status_code))
	return pdf.content


def avboka(sendify_id) -> None:
	_anrop("POST", "/shipments/cancel", {"shipment_id": sendify_id})


def hamta_sparning(sendify_id) -> list[dict]:
	return [
		{
			"tidpunkt": _tid(h["created_at"]),
			"status": h.get("status"),
			"beskrivning": h.get("description"),
			"plats": h.get("location_name"),
			"url": h.get("url"),
		}
		for h in _anrop("GET", f"/shipments/{sendify_id}/tracking") or []
	]


def kontrollera_nyckel(installningar=None) -> str:
	return _dict_svar(_anrop("GET", "/status", installningar=installningar)).get("team")
