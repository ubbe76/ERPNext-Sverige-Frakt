from datetime import date, datetime
from unittest.mock import patch

import frappe
from erpnext_sverige.tests.utils import COMPANY
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import FraktFel, fraktpris, parter
from erpnext_sverige_frakt.frakt.doctype.fraktinstallningar import fraktinstallningar
from erpnext_sverige_frakt.tests.frakt_utils import (
	aktivera_frakt,
	make_eur_pall,
	make_frakt_item,
	make_kund_med_adress,
)
from erpnext_sverige_frakt.tests.test_frakt_bokning import PRISER, SENDIFY


class TestFraktpris(IntegrationTestCase):
	def setUp(self):
		self.inst = aktivera_frakt()

	def test_kundpris_med_paslag_avrundas_till_hela_kronor(self):
		self.assertEqual(fraktpris.kundpris(127), 160)  # 127 * 1,10 + 20 = 159,7

	def test_registrera_produkter_skapar_fraktprodukt_en_gang(self):
		priser = [
			{"transportorskod": "ups_se", "transportor": "_Test UPS", "produkt": "Standard", "pris": 200.0},
			{"transportorskod": "dhl_se", "transportor": "_Test DHL", "produkt": "Paket", "pris": 100.0},
		]
		resultat = fraktpris.registrera_produkter(priser)
		self.assertEqual([p["fraktprodukt"] for p in resultat], ["_Test DHL – Paket", "_Test UPS – Standard"])
		self.assertEqual(resultat[0]["kundpris"], 130)
		fraktpris.registrera_produkter(priser)
		self.assertEqual(frappe.db.count("Fraktprodukt", {"transportor": "_Test UPS"}), 1)

	def test_part_fran_adress_och_kontakt(self):
		kund = make_kund_med_adress()
		adress = frappe.db.get_value("Address", {"address_title": f"{kund} leverans"})
		kontakt = frappe.db.get_value("Contact", {"first_name": f"{kund} kontakt"})
		p = parter.part("Kund AB", adress, kontakt, privatperson=False)
		self.assertEqual(
			{k: p[k] for k in ("namn", "adressrad_1", "postnummer", "ort", "landskod", "telefon", "epost")},
			{
				"namn": "Kund AB",
				"adressrad_1": "Testgatan 1",
				"postnummer": "41107",
				"ort": "Göteborg",
				"landskod": "SE",
				"telefon": "0701234567",
				"epost": "test@example.com",
			},
		)

	def test_nasta_upphamtningsdag_hoppar_over_helg(self):
		inst = frappe.get_doc("Fraktinstallningar")
		self.assertEqual(
			parter.nasta_upphamtningsdag(inst, date(2026, 10, 2)), date(2026, 10, 5)
		)  # fre → mån
		self.assertEqual(parter.nasta_upphamtningsdag(inst, date(2026, 10, 5)), date(2026, 10, 6))

	def test_upphamtningstid(self):
		self.assertEqual(parter.upphamtningstid("2026-10-05", "09:30:00"), datetime(2026, 10, 5, 9, 30))


class TestPrisforfragan(IntegrationTestCase):
	def setUp(self):
		aktivera_frakt()
		self.kund = make_kund_med_adress()
		self.artikel = make_frakt_item(
			"_Test Frakt Pallvara",
			fraktsatt="Förpackning",
			forpackningstyp=make_eur_pall(),
			antal_per_forpackning=40,
			weight_per_unit=2,
		)

	def order(self):
		leverans = frappe.utils.add_days(frappe.utils.today(), 7)
		return frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": COMPANY,
				"customer": self.kund,
				"delivery_date": leverans,
				"shipping_address_name": frappe.db.get_value(
					"Address", {"address_title": f"{self.kund} leverans"}
				),
				"items": [{"item_code": self.artikel, "qty": 60, "rate": 100, "delivery_date": leverans}],
			}
		).insert()

	def test_kontrollera_skapar_och_raderar_tillfallig_sandning(self):
		so = self.order()
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="TMP1") as skapa,
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])),
			patch(f"{SENDIFY}.radera_sandning") as radera,
		):
			svar = fraktpris.kontrollera("Sales Order", so.name)
		self.assertEqual(skapa.call_args.args[0]["kollin"][0]["antal"], 2)
		radera.assert_called_once_with("TMP1")
		self.assertEqual([p["transportor"] for p in svar["priser"]], ["_Test DSV", "_Test DHL"])

	def test_upphamtning_ar_aldrig_fore_nasta_arbetsdag(self):
		so = self.order()
		frappe.db.set_value(
			"Sales Order", so.name, "delivery_date", frappe.utils.add_days(frappe.utils.today(), -10)
		)
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="TMP1"),
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])) as priser,
			patch(f"{SENDIFY}.radera_sandning"),
		):
			fraktpris.kontrollera("Sales Order", so.name)
		onskad = priser.call_args.args[1]
		self.assertGreaterEqual(
			onskad.date(), parter.nasta_upphamtningsdag(frappe.get_doc("Fraktinstallningar"))
		)

	def test_tillfallig_sandning_raderas_aven_vid_fel(self):
		so = self.order()
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="TMP1"),
			patch(f"{SENDIFY}.hamta_priser", side_effect=FraktFel("Route not supported")),
			patch(f"{SENDIFY}.radera_sandning") as radera,
		):
			self.assertRaises(frappe.ValidationError, fraktpris.kontrollera, "Sales Order", so.name)
		radera.assert_called_once_with("TMP1")

	def test_lagg_till_frakt_pa_utkast_lagger_till_och_uppdaterar_artikelrad(self):
		so = self.order()
		frappe.get_doc({"doctype": "Fraktprodukt", "transportor": "_Test DSV", "produkt": "Pall"}).insert(
			ignore_if_duplicate=True
		)
		fraktpris.lagg_till_frakt("Sales Order", so.name, "_Test DSV – Pall", 900)
		fraktpris.lagg_till_frakt("Sales Order", so.name, "_Test DSV – Pall", 950)
		so.reload()
		artikel = frappe.db.get_single_value("Fraktinstallningar", "fraktartikel")
		rader = [r for r in so.items if r.item_code == artikel]
		self.assertEqual([(r.qty, r.rate) for r in rader], [(1, 950)])
		self.assertEqual(rader[0].description, "Frakt _Test DSV Pall")
		self.assertEqual(rader[0].delivery_date, so.items[0].delivery_date)
		self.assertEqual([t for t in so.taxes if t.charge_type == "Actual"], [])
		self.assertEqual(so.fraktprodukt, "_Test DSV – Pall")

	def test_kontrollera_foreslar_inte_kollin_for_fraktartikeln(self):
		so = self.order()
		fraktpris.lagg_till_frakt("Sales Order", so.name, "_Test DSV – Pall", 900)
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="TMP1") as skapa,
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])),
			patch(f"{SENDIFY}.radera_sandning"),
		):
			fraktpris.kontrollera("Sales Order", so.name)
		self.assertEqual(skapa.call_args.args[0]["kollin"][0]["antal"], 2)
		self.assertEqual(len(skapa.call_args.args[0]["kollin"]), 1)

	def test_lagg_till_frakt_pa_godkand_order_vagras(self):
		so = self.order()
		so.submit()
		self.assertRaises(
			frappe.ValidationError, fraktpris.lagg_till_frakt, "Sales Order", so.name, "_Test DSV – Pall", 900
		)

	def test_hamta_transportorsprodukter(self):
		with (
			patch(f"{SENDIFY}.skapa_sandning", return_value="TMP2"),
			patch(f"{SENDIFY}.hamta_priser", return_value=([dict(p) for p in PRISER], [])),
			patch(f"{SENDIFY}.radera_sandning"),
		):
			self.assertEqual(fraktinstallningar.hamta_transportorsprodukter(), 2)
		self.assertTrue(frappe.db.exists("Fraktprodukt", "_Test DHL – Pall"))
