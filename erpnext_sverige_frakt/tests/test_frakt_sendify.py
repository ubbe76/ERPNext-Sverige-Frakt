from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import FraktFel, sendify

NYCKEL = "hemlig-nyckel-123"
PART = {
	"namn": "Avsändare AB",
	"adressrad_1": "Gatan 1",
	"adressrad_2": "",
	"postnummer": "41107",
	"ort": "Göteborg",
	"landskod": "SE",
	"kontakt_namn": "Anna",
	"telefon": "0701234567",
	"epost": "anna@example.com",
	"privatperson": False,
}
KOLLI = {
	"kollityp": "Pall",
	"langd_cm": 120,
	"bredd_cm": 80,
	"hojd_cm": 150,
	"vikt_kg": 95.0,
	"antal": 3,
	"stapelbar": 0,
	"flakmeter": 0.4,
	"beskrivning": "Varor",
}
SANDNING = {
	"avsandare": PART,
	"mottagare": {**PART, "namn": "Kund AB", "privatperson": True},
	"kollin": [KOLLI],
	"referens_id": "SHIP-0001",
	"avsandarens_referens": "DN-0001",
	"mottagarens_referens": "",
}


def svar(status=200, data=None, headers=None, content=b"x"):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = data if data is not None else {}
	r.headers = headers or {"X-Sendify-Request-ID": "req-1"}
	r.content = content
	r.text = str(data)
	return r


class TestSendify(IntegrationTestCase):
	def setUp(self):
		inst = frappe._dict(miljo="Sandlåda", get_password=lambda falt: NYCKEL)
		self.inst = patch("erpnext_sverige_frakt.frakt.sendify.hamta_installningar", return_value=inst)
		self.inst.start()
		self.addCleanup(self.inst.stop)

	def test_skapa_sandning_skickar_sendifys_format(self):
		with patch(
			"erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(201, {"id": "S1"})
		) as req:
			self.assertEqual(sendify.skapa_sandning(SANDNING), "S1")
		metod, url = req.call_args.args
		body = req.call_args.kwargs["json"]
		self.assertEqual((metod, url), ("POST", "https://app.dev.sendify.se/external/v1/shipments"))
		self.assertEqual(req.call_args.kwargs["headers"]["x-api-key"], NYCKEL)
		self.assertTrue(body["enable_bookable_validation"])
		self.assertEqual(body["to"]["is_private_individual"], True)
		self.assertEqual(body["sender_reference"], "DN-0001")
		self.assertNotIn("receiver_reference", body)  # tomma värden skickas inte
		self.assertNotIn("address_line_2", body["from"]["address"])
		self.assertEqual(
			body["packages"][0],
			{
				"depth_cm": 120,
				"width_cm": 80,
				"height_cm": 150,
				"weight_kg": 95.0,
				"quantity": 3,
				"type": "PALLET",
				"stackable": False,
				"description": "Varor",
				"loading_meters": 0.4,
			},
		)

	def test_hamta_priser_oversatter_svaret(self):
		data = {
			"rates": [
				{
					"booking_token": "T1",
					"carrier_code": "ups_se",
					"carrier_name": "UPS Sweden",
					"product_name": "UPS Standard",
					"price": "127",
					"currency": "SEK",
					"transport_business_days_min": 2,
					"transport_business_days_max": 3,
					"expires_at": "2026-10-02T11:41:56Z",
					"pickup": {"date": "2026-10-02"},
					"estimated_delivery": {"earliest_date": "2026-10-05"},
				}
			],
			"warnings": [
				{
					"carrier_name": "DHL",
					"carrier_product_code": "dhl",
					"warnings": ["Name too long", "Phone missing"],
				}
			],
		}
		with patch(
			"erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(200, data)
		) as req:
			priser, varningar = sendify.hamta_priser("S1", datetime(2026, 10, 2, 9, 0))
		self.assertEqual(req.call_args.kwargs["json"]["shipment_id"], "S1")
		self.assertTrue(
			req.call_args.kwargs["json"]["requested_pickup_time"].startswith("2026-10-02T09:00:00+0")
		)
		self.assertEqual(priser[0]["pris"], 127.0)
		self.assertEqual(
			(priser[0]["token"], priser[0]["transportor"], priser[0]["produkt"]),
			("T1", "UPS Sweden", "UPS Standard"),
		)
		self.assertEqual(varningar, ["DHL: Name too long; Phone missing"])

	def test_valideringsfel_far_svenska_faltnamn(self):
		data = {
			"errors": {
				"packages[0].weight_kg": ["The field is required."],
				"to.contact.email": ["Invalid email."],
			}
		}
		with patch("erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(422, data)):
			with self.assertRaises(FraktFel) as fel:
				sendify.skapa_sandning(SANDNING)
		self.assertIn("Kolli 1: vikt: The field is required.", fel.exception.falt_fel)
		self.assertIn("Mottagare: e-post: Invalid email.", fel.exception.falt_fel)
		self.assertEqual(fel.exception.request_id, "req-1")

	def test_serverfel_och_natverksfel(self):
		with patch("erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(503, {})):
			self.assertRaisesRegex(FraktFel, "Sendify svarar inte", sendify.skapa_sandning, SANDNING)
		with patch(
			"erpnext_sverige_frakt.frakt.sendify.requests.request",
			side_effect=sendify.requests.ConnectionError(),
		):
			self.assertRaisesRegex(FraktFel, "Sendify svarar inte", sendify.skapa_sandning, SANDNING)

	def test_nyckeln_loggas_aldrig(self):
		with (
			patch(
				"erpnext_sverige_frakt.frakt.sendify.requests.request",
				return_value=svar(400, {"message": "Bad"}),
			),
			patch("erpnext_sverige_frakt.frakt.sendify.frappe.log_error") as logg,
		):
			self.assertRaises(FraktFel, sendify.skapa_sandning, SANDNING)
		self.assertTrue(logg.called)
		self.assertNotIn(NYCKEL, str(logg.call_args))

	def test_fel_loggas_med_defer_insert(self):
		with (
			patch(
				"erpnext_sverige_frakt.frakt.sendify.requests.request",
				return_value=svar(400, {"message": "Bad"}),
			),
			patch("erpnext_sverige_frakt.frakt.sendify.frappe.log_error") as logg,
		):
			self.assertRaises(FraktFel, sendify.skapa_sandning, SANDNING)
		self.assertTrue(logg.call_args.kwargs.get("defer_insert"))

	def test_felformer_hanteras(self):
		fall = [
			({"errors": ["Fel ett", "Fel två"]}, ["Fel ett", "Fel två"]),
			({"errors": [{"field": "to.contact.email", "message": "Invalid email."}]}, None),
			({"errors": "Bara text"}, ["Bara text"]),
			(["listsvar"], []),
			("textsvar", []),
		]
		for data, forvantat in fall:
			with self.subTest(data=data):
				with patch(
					"erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(422, data)
				):
					with self.assertRaises(FraktFel) as fel:
						sendify.skapa_sandning(SANDNING)
				if forvantat is not None:
					self.assertEqual(fel.exception.falt_fel, forvantat)
				else:
					self.assertEqual(fel.exception.falt_fel, ["Mottagare: e-post: Invalid email."])

	def test_4xx_utan_json(self):
		r = svar(400)
		r.json.side_effect = ValueError("no json")
		with patch("erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=r):
			self.assertRaisesRegex(FraktFel, "HTTP 400", sendify.skapa_sandning, SANDNING)

	def test_tomt_eller_ogiltigt_2xx_svar_ger_fraktfel(self):
		tomt = svar(200, None, content=b"")
		ogiltigt = svar(200)
		ogiltigt.json.side_effect = ValueError("no json")
		lista = svar(200, ["x"])
		anrop = [
			lambda: sendify.skapa_sandning(SANDNING),
			lambda: sendify.hamta_priser("S1", datetime(2026, 10, 5, 9)),
			lambda: sendify.boka("T1"),
			lambda: sendify.hamta_dokument("S1", "label"),
			lambda: sendify.kontrollera_nyckel(),
		]
		for r in (tomt, ogiltigt, lista):
			for a in anrop:
				with patch("erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=r):
					self.assertRaisesRegex(FraktFel, "oväntat svar", a)

	def test_boka_timeout_har_eget_meddelande(self):
		with patch(
			"erpnext_sverige_frakt.frakt.sendify.requests.request", side_effect=sendify.requests.Timeout()
		):
			self.assertRaisesRegex(FraktFel, "Bokningen kan ha genomförts", sendify.boka, "T1")

	def test_boka_och_dokument(self):
		with patch(
			"erpnext_sverige_frakt.frakt.sendify.requests.request",
			return_value=svar(
				200,
				{
					"shipment_id": "S1",
					"main_tracking_id": "TRK1",
					"available_document_types": ["label", "waybill"],
				},
			),
		):
			self.assertEqual(
				sendify.boka("T1"), {"sparningsnummer": "TRK1", "dokumenttyper": ["label", "waybill"]}
			)
		with (
			patch(
				"erpnext_sverige_frakt.frakt.sendify.requests.request",
				return_value=svar(200, {"output_url": "https://x/doc.pdf"}),
			) as req,
			patch(
				"erpnext_sverige_frakt.frakt.sendify.requests.get", return_value=svar(200, content=b"%PDF")
			),
		):
			self.assertEqual(sendify.hamta_dokument("S1", "label"), b"%PDF")
		self.assertEqual(
			req.call_args.kwargs["json"],
			{"shipment_ids": ["S1"], "document_type": "label", "label_layout": "a4", "output_format": "url"},
		)

	def test_sparning_tolkar_tid_med_nanosekunder(self):
		data = [
			{
				"ID": "TRK1",
				"url": "https://sendify/t/S1",
				"status": "ORDERED",
				"description": "Booked",
				"location_name": "Göteborg",
				"created_at": "2026-10-01T09:17:29.754885247Z",
			}
		]
		with patch("erpnext_sverige_frakt.frakt.sendify.requests.request", return_value=svar(200, data)):
			handelser = sendify.hamta_sparning("S1")
		self.assertEqual(handelser[0]["status"], "ORDERED")
		self.assertEqual(
			handelser[0]["tidpunkt"].replace(microsecond=0), datetime(2026, 10, 1, 11, 17, 29)
		)  # CEST
		self.assertEqual(handelser[0]["url"], "https://sendify/t/S1")
