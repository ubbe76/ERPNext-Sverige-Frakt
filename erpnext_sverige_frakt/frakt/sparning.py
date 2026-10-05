"""Spårning av bokade försändelser."""

from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime

from erpnext_sverige_frakt.frakt import leverantor, visa_fraktfel

LEVERERAD = "DELIVERED"
INTERVALL_TIMMAR = {"Varje timme": 1, "Var fjärde timme": 4, "Dagligen": 24}


def uppdatera_shipment(doc) -> None:
	handelser = sorted(leverantor().hamta_sparning(doc.sendify_id), key=lambda h: h["tidpunkt"])
	if not handelser:
		return
	kanda = {(get_datetime(h.tidpunkt), h.status) for h in doc.sparningshandelser}
	for h in handelser:
		if (get_datetime(h["tidpunkt"]), h["status"]) not in kanda:
			doc.append(
				"sparningshandelser",
				{
					"tidpunkt": h["tidpunkt"],
					"status": h["status"],
					"beskrivning": h["beskrivning"],
					"plats": h["plats"],
				},
			)
	senaste = handelser[-1]
	doc.senaste_sparning = (
		f"{senaste['beskrivning']} ({senaste['plats']})" if senaste["plats"] else senaste["beskrivning"]
	)
	doc.senaste_sparningsstatus = senaste["status"]
	doc.save(ignore_permissions=True)
	if senaste.get("url"):
		doc.db_set("tracking_url", senaste["url"])
	if senaste["status"] == LEVERERAD:
		doc.db_set({"tracking_status": "Delivered", "status": "Completed"})
	else:
		doc.db_set("tracking_status", "In Progress")


@frappe.whitelist()
@visa_fraktfel
def uppdatera(shipment: str) -> None:
	doc = frappe.get_doc("Shipment", shipment)
	doc.check_permission("read")
	if doc.sendify_id and doc.docstatus == 1:
		uppdatera_shipment(doc)


def uppdatera_alla() -> None:
	inst = frappe.get_cached_doc("Fraktinstallningar")
	if not inst.aktiverad:
		return
	timmar = INTERVALL_TIMMAR.get(inst.sparning_intervall, 1)
	if inst.senaste_sparningskorning and now_datetime() - get_datetime(
		inst.senaste_sparningskorning
	) < timedelta(hours=timmar, minutes=-5):
		return
	for namn in frappe.get_all(
		"Shipment", filters={"docstatus": 1, "status": "Booked", "sendify_id": ["is", "set"]}, pluck="name"
	):
		doc = frappe.get_doc("Shipment", namn)
		if doc.tracking_status in ("Returned", "Lost"):
			continue
		try:
			uppdatera_shipment(doc)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Sendify: spårning misslyckades för {namn}")
	frappe.db.set_single_value(
		"Fraktinstallningar", "senaste_sparningskorning", now_datetime(), update_modified=False
	)
