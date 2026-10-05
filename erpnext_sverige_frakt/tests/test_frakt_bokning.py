from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import FraktFel, bokning
from erpnext_sverige_frakt.tests.frakt_utils import (
	aktivera_frakt,
	commit_som_savepoint,
	make_eur_pall,
	make_foljesedel,
	make_frakt_item,
	make_kund_med_adress,
)

SENDIFY = "erpnext_sverige_frakt.frakt.sendify"


def _tom_pdf() -> bytes:
	# Frappe läser PDF-filer med pypdf vid sparande, så en bara rubrik räcker inte
	from io import BytesIO

	from pypdf import PdfWriter

	skrivare = PdfWriter()
	skrivare.add_blank_page(width=72, height=72)
	ut = BytesIO()
	skrivare.write(ut)
	return ut.getvalue()


TOM_PDF = _tom_pdf()


class FraktTestCase(IntegrationTestCase):
	def setUp(self):
		commit_som_savepoint(self)
		aktivera_frakt()
		self.kund = make_kund_med_adress()
		self.pall = make_eur_pall()
		self.artikel = make_frakt_item(
			"_Test Frakt Pallvara",
			fraktsatt="Förpackning",
			forpackningstyp=self.pall,
			antal_per_forpackning=40,
			weight_per_unit=2,
			uoms=[("Box", 10)],
		)
		frappe.db.set_value("Customer", self.kund, "forvald_fraktprodukt", None)

	def shipment(self, rader=None, **dn_falt):
		dn = make_foljesedel(self.kund, rader or [(self.artikel, 100)], **dn_falt)
		return frappe.get_doc("Shipment", bokning.skapa_shipment(dn.name)), dn


class TestSkapaShipment(FraktTestCase):
	def test_shipment_far_kollin_referenser_och_avsandare(self):
		doc, dn = self.shipment(po_no="KUND-PO-7")
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual([r.delivery_note for r in doc.shipment_delivery_note], [dn.name])
		self.assertEqual((doc.avsandarens_referens, doc.mottagarens_referens), (dn.name, "KUND-PO-7"))
		self.assertEqual(
			doc.pickup_address_name, frappe.db.get_single_value("Fraktinstallningar", "avsandaradress")
		)
		self.assertEqual(len(doc.shipment_parcel), 1)
		p = doc.shipment_parcel[0]
		self.assertEqual((p.kollityp, p.count, p.length, p.width, p.height), ("Pall", 3, 120, 80, 150))
		self.assertGreater(doc.value_of_goods, 0)

	def test_kollforslaget_hoppar_over_fraktartikeln(self):
		from erpnext_sverige_frakt.frakt.artikel import FRAKTARTIKEL

		utan, _dn = self.shipment()
		med, _dn = self.shipment(rader=[(self.artikel, 100), (FRAKTARTIKEL, 1)])
		self.assertEqual(
			[(p.kollityp, p.count) for p in med.shipment_parcel],
			[(p.kollityp, p.count) for p in utan.shipment_parcel],
		)

	def test_kollin_raknas_pa_lagerantal(self):
		doc, _dn = self.shipment(rader=[(self.artikel, 8, "Box")])  # 80 st = 2 pallar
		self.assertEqual(doc.shipment_parcel[0].count, 2)

	def test_kundens_forval_forvaljs(self):
		namn = "_Test DSV – Pall"
		if frappe.db.exists("Fraktprodukt", namn):
			produkt = frappe.get_doc("Fraktprodukt", namn)
		else:
			produkt = frappe.get_doc(
				{"doctype": "Fraktprodukt", "transportor": "_Test DSV", "produkt": "Pall"}
			).insert()
		frappe.db.set_value("Customer", self.kund, "forvald_fraktprodukt", produkt.name)
		doc, _dn = self.shipment()
		self.assertEqual(doc.fraktprodukt, produkt.name)

	def test_sandning_fran_shipment(self):
		doc, dn = self.shipment()
		s = bokning.sandning_fran_shipment(doc)
		self.assertEqual(s["referens_id"], doc.name)
		self.assertEqual(s["avsandarens_referens"], dn.name)
		self.assertEqual(s["mottagare"]["namn"], self.kund)
		self.assertEqual(s["mottagare"]["landskod"], "SE")
		self.assertEqual(s["kollin"][0]["kollityp"], "Pall")
		self.assertEqual(s["kollin"][0]["antal"], 3)

	def test_foresla_kollin_igen_ersatter_tabellen(self):
		doc, _dn = self.shipment()
		doc.shipment_parcel[0].count = 9
		doc.save()
		bokning.foresla_kollin_igen(doc.name)
		doc.reload()
		self.assertEqual(doc.shipment_parcel[0].count, 3)


PRISER = [
	{
		"token": "T-DHL",
		"transportorskod": "dhl",
		"transportor": "_Test DHL",
		"produkt": "Pall",
		"pris": 900.0,
		"valuta": "SEK",
		"dagar_min": 2,
		"dagar_max": 3,
		"upphamtning": {},
		"leverans": {},
		"giltig_till": "2099-01-01T00:00:00Z",
	},
	{
		"token": "T-DSV",
		"transportorskod": "dsv",
		"transportor": "_Test DSV",
		"produkt": "Pall",
		"pris": 800.0,
		"valuta": "SEK",
		"dagar_min": 1,
		"dagar_max": 2,
		"upphamtning": {},
		"leverans": {},
		"giltig_till": "2099-01-01T00:00:00Z",
	},
]


def _fraktprodukt(transportor):
	frappe.get_doc({"doctype": "Fraktprodukt", "transportor": transportor, "produkt": "Pall"}).insert(
		ignore_if_duplicate=True
	)


class TestPriser(FraktTestCase):
	def _priser(self):
		return patch(
			f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], ["UPS: Name too long"])
		)

	def test_hamta_priser_skapar_sandning_och_sorterar(self):
		doc, _dn = self.shipment()
		with patch(f"{SENDIFY}.skapa_sandning", return_value="S1") as skapa, self._priser():
			svar = bokning.hamta_priser(doc.name)
		self.assertEqual(skapa.call_args.args[0]["referens_id"], doc.name)
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "sendify_id"), "S1")
		self.assertEqual([p["token"] for p in svar["priser"]], ["T-DSV", "T-DHL"])
		self.assertEqual(svar["priser"][0]["kundpris"], 900)  # 800 * 1,1 + 20
		self.assertEqual(svar["varningar"], ["UPS: Name too long"])

	def test_andra_prisforfragan_uppdaterar_sandningen(self):
		doc, _dn = self.shipment()
		frappe.db.set_value("Shipment", doc.name, "sendify_id", "S1")
		with (
			patch(f"{SENDIFY}.skapa_sandning") as skapa,
			patch(f"{SENDIFY}.uppdatera_sandning") as uppdatera,
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])),
		):
			bokning.hamta_priser(doc.name)
		skapa.assert_not_called()
		self.assertEqual(uppdatera.call_args.args[0], "S1")

	def test_forvald_produkt_markeras(self):
		doc, _dn = self.shipment()
		_fraktprodukt("_Test DHL")
		frappe.db.set_value("Shipment", doc.name, "fraktprodukt", "_Test DHL – Pall")
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="S1"),
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])),
		):
			svar = bokning.hamta_priser(doc.name)
		self.assertEqual([p["forvald"] for p in svar["priser"]], [False, True])

	def test_hamta_priser_visar_sendifys_faltfel(self):
		doc, _dn = self.shipment()
		fel = FraktFel(
			"Sendify kunde inte behandla sändningen", falt_fel=["Mottagare: e-post: The field is required."]
		)
		with patch(f"{SENDIFY}.skapa_sandning", side_effect=fel):
			with self.assertRaises(frappe.ValidationError) as undantag:
				bokning.hamta_priser(doc.name)
		self.assertIn("Mottagare: e-post", str(undantag.exception))

	def test_spara_val(self):
		doc, _dn = self.shipment()
		_fraktprodukt("_Test DSV")
		bokning.spara_val(doc.name, "_Test DSV – Pall", 800, "SEK")
		doc.reload()
		self.assertEqual(
			(doc.fraktprodukt, doc.fraktpris, doc.kundpris, doc.docstatus), ("_Test DSV – Pall", 800, 900, 0)
		)
		self.assertTrue(doc.pris_hamtat)


@contextmanager
def mockad_sendify(priser=None, boka=None, dokument=TOM_PDF, sparning=None):
	with (
		patch(f"{SENDIFY}.skapa_sandning", return_value="S1"),
		patch(f"{SENDIFY}.uppdatera_sandning"),
		patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in (priser or PRISER)], [])),
		patch(
			f"{SENDIFY}.boka",
			**(
				{"side_effect": boka}
				if isinstance(boka, Exception)
				else {
					"return_value": boka or {"sparningsnummer": "TRK1", "dokumenttyper": ["label", "waybill"]}
				}
			),
		) as b,
		patch(
			f"{SENDIFY}.hamta_dokument",
			**({"side_effect": dokument} if isinstance(dokument, Exception) else {"return_value": dokument}),
		),
		patch(f"{SENDIFY}.hamta_sparning", return_value=sparning or []),
	):
		yield b


class TestBoka(FraktTestCase):
	def boka_dsv(self, doc):
		bokning.hamta_priser(doc.name)
		bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800, "SEK")
		doc.reload()

	def test_boka_uppdaterar_shipment_och_foljesedel(self):
		doc, dn = self.shipment()
		with mockad_sendify() as b:
			self.boka_dsv(doc)
		b.assert_called_once_with("T-DSV")
		self.assertEqual((doc.docstatus, doc.status), (1, "Booked"))
		self.assertEqual((doc.carrier, doc.carrier_service, doc.awb_number), ("_Test DSV", "Pall", "TRK1"))
		self.assertEqual((doc.shipment_amount, doc.kundpris, doc.service_provider), (800, 900, "Sendify"))
		self.assertEqual(
			frappe.db.get_value("Delivery Note", dn.name, ["transporter_name", "lr_no"]),
			("_Test DSV", "TRK1"),
		)
		filer = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Shipment", "attached_to_name": doc.name},
			pluck="file_name",
		)
		self.assertEqual(sorted(filer), sorted([f"Etikett-{doc.name}.pdf", f"Fraktsedel-{doc.name}.pdf"]))
		self.assertTrue(doc.etikett_hamtad)

	def test_bokad_shipment_kan_inte_bokas_igen(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			self.boka_dsv(doc)
			self.assertRaises(
				frappe.ValidationError, bokning.boka, doc.name, "T-DSV", "_Test DSV – Pall", 800
			)
		self.assertEqual(b.call_count, 1)

	def test_misslyckad_bokning_lamnar_utkast(self):
		doc, dn = self.shipment()
		with mockad_sendify(boka=FraktFel("The booking token has expired")):
			bokning.hamta_priser(doc.name)
			with self.assertRaises(frappe.ValidationError) as fel:
				bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800)
		self.assertIn("expired", str(fel.exception))
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "docstatus"), 0)
		self.assertFalse(frappe.db.get_value("Delivery Note", dn.name, "lr_no"))

	def test_fel_vid_dokumenthamtning_behaller_bokningen(self):
		doc, _dn = self.shipment()
		with mockad_sendify(dokument=FraktFel("Dokumentet kunde inte hämtas")):
			self.boka_dsv(doc)
		self.assertEqual((doc.status, doc.etikett_hamtad), ("Booked", 0))
		with mockad_sendify():
			bokning.hamta_dokument(doc.name)
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "etikett_hamtad"), 1)

	def test_ogiltigt_dokument_ger_inget_undantag(self):
		doc, _dn = self.shipment()
		with mockad_sendify(dokument=b"<html>error</html>"):
			self.boka_dsv(doc)
		self.assertEqual((doc.status, doc.etikett_hamtad), ("Booked", 0))

	def test_fel_efter_bokning_hos_sendify_bevarar_sparningsnummer(self):
		doc, _dn = self.shipment()
		with mockad_sendify():
			bokning.hamta_priser(doc.name)
			with patch("frappe.model.document.Document.submit", side_effect=RuntimeError("db")):
				with self.assertRaises(frappe.ValidationError) as fel:
					bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800)
		self.assertIn("TRK1", str(fel.exception))
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": f"Sendify: bokning {doc.name} kunde inte sparas"})
		)

	def test_boka_vald_produkt_utan_prisandring(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			bokning.hamta_priser(doc.name)
			bokning.spara_val(doc.name, "_Test DSV – Pall", 790)  # 800 är inom 5 %
			self.assertEqual(bokning.boka_vald_produkt(doc.name), {"status": "bokad"})
		b.assert_called_once_with("T-DSV")

	def test_boka_vald_produkt_med_prisandring_kraver_bekraftelse(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			bokning.hamta_priser(doc.name)
			bokning.spara_val(doc.name, "_Test DSV – Pall", 600)
			self.assertEqual(
				bokning.boka_vald_produkt(doc.name), {"status": "prisandring", "gammalt": 600, "nytt": 800}
			)
			b.assert_not_called()
			self.assertEqual(bokning.boka_vald_produkt(doc.name, bekraftat=1), {"status": "bokad"})

	def test_boka_vald_produkt_som_saknas(self):
		doc, _dn = self.shipment()
		frappe.get_doc(
			{"doctype": "Fraktprodukt", "transportor": "_Test PostNord", "produkt": "Pall"}
		).insert(ignore_if_duplicate=True)
		frappe.db.set_value("Shipment", doc.name, "fraktprodukt", "_Test PostNord – Pall")
		with mockad_sendify() as b:
			svar = bokning.boka_vald_produkt(doc.name)
		self.assertEqual(svar["status"], "saknas")
		self.assertEqual(len(svar["priser"]), 2)
		b.assert_not_called()


class TestGranskningsfixar(FraktTestCase):
	def test_boka_kraver_godsvarde_fore_sendify(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			bokning.hamta_priser(doc.name)
			frappe.db.set_value("Shipment", doc.name, "value_of_goods", 0)
			with self.assertRaises(frappe.ValidationError) as fel:
				bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800)
		self.assertIn("Godsvärdet", str(fel.exception))
		b.assert_not_called()

	def test_boka_kraver_kollin_fore_sendify(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			bokning.hamta_priser(doc.name)
			frappe.db.delete("Shipment Parcel", {"parent": doc.name})
			self.assertRaises(
				frappe.ValidationError, bokning.boka, doc.name, "T-DSV", "_Test DSV – Pall", 800
			)
		b.assert_not_called()

	def test_kundpris_raknas_om_efter_prisandring(self):
		doc, _dn = self.shipment()
		with mockad_sendify() as b:
			bokning.hamta_priser(doc.name)
			bokning.spara_val(doc.name, "_Test DSV – Pall", 600)
			bokning.boka_vald_produkt(doc.name, bekraftat=1)
		b.assert_called_once()
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "kundpris"), 900)  # 800 * 1,1 + 20

	def test_manuellt_andrat_kundpris_bevaras(self):
		doc, _dn = self.shipment()
		with mockad_sendify():
			bokning.hamta_priser(doc.name)
			bokning.spara_val(doc.name, "_Test DSV – Pall", 800)
			frappe.db.set_value("Shipment", doc.name, "kundpris", 750)
			bokning.boka_vald_produkt(doc.name, bekraftat=1)
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "kundpris"), 750)

	def test_kollin_utan_vikt_ger_svenskt_fel(self):
		inte_vikt = make_frakt_item(
			"_Test Frakt Utan Vikt",
			fraktsatt="Egna mått",
			frakt_langd_cm=10,
			frakt_bredd_cm=10,
			frakt_hojd_cm=10,
			weight_per_unit=0,
		)
		dn = make_foljesedel(self.kund, [(inte_vikt, 1)])
		with self.assertRaises(frappe.ValidationError) as fel:
			bokning.skapa_shipment(dn.name)
		self.assertIn("saknar vikt", str(fel.exception))

	def test_foresla_kollin_igen_med_viktlost_artikel_ger_svenskt_fel(self):
		doc, _dn = self.shipment()
		inte_vikt = make_frakt_item(
			"_Test Frakt Utan Vikt",
			fraktsatt="Egna mått",
			frakt_langd_cm=10,
			frakt_bredd_cm=10,
			frakt_hojd_cm=10,
			weight_per_unit=0,
		)
		with patch.object(bokning, "_lagerrader", return_value=[(inte_vikt, 1)]):
			with self.assertRaises(frappe.ValidationError) as fel:
				bokning.foresla_kollin_igen(doc.name)
		self.assertIn("saknar vikt", str(fel.exception))


class TestAvboka(FraktTestCase):
	def bokad(self):
		doc, dn = self.shipment()
		with mockad_sendify():
			bokning.hamta_priser(doc.name)
			bokning.boka(doc.name, "T-DSV", "_Test DSV – Pall", 800)
		return frappe.get_doc("Shipment", doc.name), dn

	def test_avbryt_avbokar_hos_sendify_och_tommer_foljesedeln(self):
		doc, dn = self.bokad()
		with patch(f"{SENDIFY}.avboka") as avboka:
			doc.cancel()
		avboka.assert_called_once_with("S1")
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "status"), "Cancelled")
		self.assertFalse(frappe.db.get_value("Delivery Note", dn.name, "lr_no"))

	def test_vagrad_avbokning_stoppar_avbrytandet(self):
		doc, _dn = self.bokad()
		with patch(f"{SENDIFY}.avboka", side_effect=FraktFel("Shipment already picked up")):
			self.assertRaises(frappe.ValidationError, doc.cancel)
		self.assertEqual(frappe.db.get_value("Shipment", doc.name, "docstatus"), 1)

	def test_radera_utkast_raderar_hos_sendify(self):
		doc, _dn = self.shipment()
		frappe.db.set_value("Shipment", doc.name, "sendify_id", "S9")
		with patch(f"{SENDIFY}.radera_sandning") as radera:
			frappe.delete_doc("Shipment", doc.name)
		radera.assert_called_once_with("S9")
