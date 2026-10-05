import frappe
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt.kollin import foresla_kollin
from erpnext_sverige_frakt.tests.frakt_utils import make_eur_pall, make_frakt_item


class TestArtikelvalidering(IntegrationTestCase):
	def test_pallplatser_fyller_flakmeter(self):
		item = make_frakt_item(
			"_Test Frakt Maskin",
			fraktsatt="Egna mått",
			frakt_pallplatser=2,
			frakt_kollityp="Pall",
			frakt_langd_cm=240,
			frakt_bredd_cm=80,
			frakt_hojd_cm=150,
			weight_per_unit=400,
		)
		self.assertAlmostEqual(frappe.db.get_value("Item", item, "frakt_flakmeter"), 0.8)

	def test_forpackning_kraver_antal_per_forpackning(self):
		self.assertRaises(
			frappe.ValidationError,
			make_frakt_item,
			"_Test Frakt Utan Antal",
			fraktsatt="Förpackning",
			forpackningstyp=make_eur_pall(),
			antal_per_forpackning=0,
		)


class TestKolliforslag(IntegrationTestCase):
	def setUp(self):
		self.pall = make_eur_pall()
		self.a = make_frakt_item(
			"_Test Frakt A",
			fraktsatt="Förpackning",
			forpackningstyp=self.pall,
			antal_per_forpackning=40,
			weight_per_unit=2,
		)
		self.b = make_frakt_item(
			"_Test Frakt B",
			fraktsatt="Förpackning",
			forpackningstyp=self.pall,
			antal_per_forpackning=20,
			weight_per_unit=1,
		)
		self.c = make_frakt_item("_Test Frakt C", fraktsatt="", weight_per_unit=5)

	def test_egna_matt_ger_en_rad_per_artikel(self):
		item = make_frakt_item(
			"_Test Frakt Låda",
			fraktsatt="Egna mått",
			frakt_kollityp="Paket",
			frakt_langd_cm=30,
			frakt_bredd_cm=20,
			frakt_hojd_cm=10,
			weight_per_unit=1.5,
		)
		kollin, varningar = foresla_kollin([(item, 2)])
		self.assertEqual(varningar, [])
		self.assertEqual(len(kollin), 1)
		k = kollin[0]
		self.assertEqual(
			(k["kollityp"], k["langd_cm"], k["bredd_cm"], k["hojd_cm"], k["antal"]), ("Paket", 30, 20, 10, 2)
		)
		self.assertAlmostEqual(k["vikt_kg"], 1.5)

	def test_forpackningar_fylls_ihop(self):
		kollin, _ = foresla_kollin([(self.a, 100), (self.b, 10)])  # 2,5 + 0,5 pall
		self.assertEqual(len(kollin), 1)
		k = kollin[0]
		self.assertEqual(
			(k["kollityp"], k["antal"], k["langd_cm"], k["bredd_cm"], k["hojd_cm"]), ("Pall", 3, 120, 80, 150)
		)
		self.assertAlmostEqual(k["vikt_kg"], 25 + (200 + 10) / 3, places=2)
		self.assertAlmostEqual(k["flakmeter"], 0.4)
		self.assertEqual(k["beskrivning"], "_Test Frakt A, _Test Frakt B")

	def test_exakt_full_forpackning_avrundas_inte_upp(self):
		kollin, _ = foresla_kollin([(self.a, 80)])
		self.assertEqual(kollin[0]["antal"], 2)

	def test_artikel_utan_fraktsatt_laggs_pa_forpackningen(self):
		kollin, varningar = foresla_kollin([(self.a, 40), (self.c, 3)])
		self.assertEqual(len(kollin), 1)
		self.assertAlmostEqual(kollin[0]["vikt_kg"], 25 + 80 + 15)
		self.assertIn("_Test Frakt C saknar fraktsätt", varningar)

	def test_artikel_utan_fraktsatt_och_utan_forpackning_blir_ovrigt(self):
		kollin, _ = foresla_kollin([(self.c, 3)])
		self.assertEqual(len(kollin), 1)
		self.assertEqual((kollin[0]["kollityp"], kollin[0]["antal"], kollin[0]["langd_cm"]), ("Övrigt", 1, 0))
		self.assertAlmostEqual(kollin[0]["vikt_kg"], 15)

	def test_inga_kollin_utan_vikt(self):
		item = make_frakt_item("_Test Frakt Viktlös", fraktsatt="", weight_per_unit=0)
		kollin, varningar = foresla_kollin([(item, 1)])
		self.assertEqual(kollin, [])
		self.assertIn("_Test Frakt Viktlös saknar vikt", varningar)

	def test_vikt_i_gram_raknas_om_till_kg(self):
		item = make_frakt_item(
			"_Test Frakt Gram",
			weight_uom="Gram",
			fraktsatt="Egna mått",
			frakt_kollityp="Paket",
			frakt_langd_cm=10,
			frakt_bredd_cm=10,
			frakt_hojd_cm=10,
			weight_per_unit=500,
		)
		kollin, _ = foresla_kollin([(item, 4)])
		self.assertAlmostEqual(kollin[0]["vikt_kg"], 0.5)

	def test_egna_matt_utan_matt_ger_varning(self):
		item = make_frakt_item(
			"_Test Frakt Måttlös",
			fraktsatt="Egna mått",
			frakt_kollityp="Paket",
			weight_per_unit=1,
			frakt_langd_cm=0,
			frakt_bredd_cm=0,
			frakt_hojd_cm=0,
		)
		_kollin, varningar = foresla_kollin([(item, 1)])
		self.assertIn("_Test Frakt Måttlös saknar mått", varningar)
