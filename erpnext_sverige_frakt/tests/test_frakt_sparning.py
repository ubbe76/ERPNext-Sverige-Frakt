from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from erpnext_sverige_frakt.frakt import bokning, sparning
from erpnext_sverige_frakt.tests.test_frakt_bokning import SENDIFY, FraktTestCase, mockad_sendify


def handelse(status, timme, beskrivning="Händelse"):
	return {
		"tidpunkt": datetime(2026, 10, 5, timme),
		"status": status,
		"beskrivning": beskrivning,
		"plats": "Borås",
		"url": "https://sendify/t/S1",
	}


class TestSparning(FraktTestCase):
	def bokad(self):
		doc, _dn = self.shipment()
		with mockad_sendify():
			bokning.hamta_priser(doc.name)
			bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800)
		return doc.name

	def test_nya_handelser_laggs_till_en_gang(self):
		namn = self.bokad()
		with patch(
			f"{SENDIFY}.hamta_sparning",
			return_value=[handelse("ORDERED", 8), handelse("IN_TRANSIT", 12, "På väg")],
		):
			sparning.uppdatera(namn)
			sparning.uppdatera(namn)
		doc = frappe.get_doc("Shipment", namn)
		self.assertEqual([h.status for h in doc.sparningshandelser], ["ORDERED", "IN_TRANSIT"])
		self.assertEqual((doc.tracking_status, doc.senaste_sparningsstatus), ("In Progress", "IN_TRANSIT"))
		self.assertEqual(doc.senaste_sparning, "På väg (Borås)")
		self.assertEqual(doc.tracking_url, "https://sendify/t/S1")

	def test_levererad_slutfor_shipment(self):
		namn = self.bokad()
		with patch(f"{SENDIFY}.hamta_sparning", return_value=[handelse("DELIVERED", 14, "Levererad")]):
			sparning.uppdatera(namn)
		self.assertEqual(
			frappe.db.get_value("Shipment", namn, ["tracking_status", "status"]), ("Delivered", "Completed")
		)

	def test_schemalagt_jobb_respekterar_intervall(self):
		namn = self.bokad()
		frappe.db.set_single_value(
			"Fraktinstallningar",
			{
				"sparning_intervall": "Var fjärde timme",
				"senaste_sparningskorning": now_datetime() - timedelta(hours=1),
			},
		)
		frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
		with patch(f"{SENDIFY}.hamta_sparning", return_value=[handelse("IN_TRANSIT", 12)]) as hamta:
			sparning.uppdatera_alla()
			hamta.assert_not_called()
			frappe.db.set_single_value(
				"Fraktinstallningar", "senaste_sparningskorning", now_datetime() - timedelta(hours=5)
			)
			frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
			sparning.uppdatera_alla()
		self.assertIn("S1", [c.args[0] for c in hamta.call_args_list])
		self.assertEqual(frappe.db.get_value("Shipment", namn, "tracking_status"), "In Progress")

	def test_oväntat_fel_for_en_forsandelse_stoppar_inte_jobbet(self):
		self.bokad()
		frappe.db.set_single_value("Fraktinstallningar", "senaste_sparningskorning", None)
		frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
		with patch(f"{SENDIFY}.hamta_sparning", side_effect=ValueError("trasigt")):
			sparning.uppdatera_alla()
		self.assertTrue(frappe.db.get_single_value("Fraktinstallningar", "senaste_sparningskorning"))
