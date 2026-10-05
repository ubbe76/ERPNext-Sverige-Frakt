"""Röktest mot Sendifys sandlåda. Körs bara om sendify_sandbox_api_key finns i site_config."""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import sendify
from erpnext_sverige_frakt.frakt.parter import forsta_upphamtning

NYCKEL = frappe.conf.get("sendify_sandbox_api_key")
PART = {
	"adressrad_1": "Testgatan 1",
	"postnummer": "41107",
	"ort": "Göteborg",
	"landskod": "SE",
	"kontakt_namn": "Test Testsson",
	"telefon": "0701234567",
	"epost": "test@example.com",
	"privatperson": False,
}


@unittest.skipUnless(NYCKEL, "sendify_sandbox_api_key saknas i site_config")
class TestSendifySandlada(IntegrationTestCase):
	def setUp(self):
		inst = frappe._dict(miljo="Sandlåda", get_password=lambda falt: NYCKEL)
		p = patch("erpnext_sverige_frakt.frakt.sendify.hamta_installningar", return_value=inst)
		p.start()
		self.addCleanup(p.stop)

	def test_hela_flodet(self):
		self.assertTrue(sendify.kontrollera_nyckel())
		sandning = {
			"avsandare": {**PART, "namn": "ERPNext Test AB"},
			"mottagare": {
				**PART,
				"namn": "Mottagare AB",
				"adressrad_1": "Drottninggatan 1",
				"postnummer": "11151",
				"ort": "Stockholm",
			},
			"kollin": [
				{
					"kollityp": "Paket",
					"langd_cm": 40,
					"bredd_cm": 30,
					"hojd_cm": 20,
					"vikt_kg": 5,
					"antal": 1,
					"stapelbar": 1,
					"flakmeter": 0,
					"beskrivning": "Testgods",
				}
			],
			"referens_id": "erpnext-sandlada",
			"avsandarens_referens": "DN-TEST",
		}
		sendify_id = sendify.skapa_sandning(sandning)
		priser, _varningar = sendify.hamta_priser(
			sendify_id, forsta_upphamtning(frappe.get_doc("Fraktinstallningar"))
		)
		self.assertTrue(priser, "inga priser i sandlådan")
		valt = next(
			p
			for p in priser
			if any(t in (p["transportorskod"] or p["transportor"]).lower() for t in ("dhl", "ups", "dsv"))
		)
		bokad = sendify.boka(valt["token"])
		self.assertTrue(bokad["sparningsnummer"])
		self.assertTrue(sendify.hamta_dokument(sendify_id, "label").startswith(b"%PDF"))
		self.assertEqual(sendify.hamta_sparning(sendify_id)[0]["status"], "ORDERED")
		sendify.avboka(sendify_id)
