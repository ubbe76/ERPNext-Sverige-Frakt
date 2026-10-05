import frappe
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import FraktFel, hamta_installningar, visa_fraktfel


class TestFraktDoctypes(IntegrationTestCase):
	def test_fraktprodukt_namnges_efter_transportor_och_produkt(self):
		doc = frappe.get_doc(
			{"doctype": "Fraktprodukt", "transportor": "_Test Frakt AB", "produkt": "Paket Express"}
		).insert()
		self.assertEqual(doc.name, "_Test Frakt AB – Paket Express")

	def test_forpackningstyp_kraver_matt(self):
		doc = frappe.get_doc(
			{
				"doctype": "Forpackningstyp",
				"forpackningstyp_namn": "_Test noll",
				"langd_cm": 0,
				"bredd_cm": 80,
				"hojd_cm": 100,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_inaktiverade_installningar_ger_fel(self):
		frappe.db.set_single_value("Fraktinstallningar", "aktiverad", 0)
		frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
		self.assertRaises(frappe.ValidationError, hamta_installningar)

	def test_visa_fraktfel_blir_valideringsfel_med_faltlista(self):
		@visa_fraktfel
		def misslyckas():
			raise FraktFel(
				"Ogiltig sändning", falt_fel=["Kolli 1: vikt: The field is required."], request_id="abc"
			)

		with self.assertRaises(frappe.ValidationError) as fel:
			misslyckas()
		self.assertIn("Kolli 1: vikt", str(fel.exception))
		self.assertIn("abc", str(fel.exception))

	def test_request_id_escapas(self):
		html = FraktFel("Fel", request_id="<script>x</script>").som_html()
		self.assertNotIn("<script>", html)
		self.assertIn("&lt;script&gt;", html)

	def test_bootinfo_visar_om_frakt_ar_aktiverad(self):
		from erpnext_sverige_frakt.frakt.boot import extend_bootinfo

		for varde in (0, 1):
			frappe.db.set_single_value("Fraktinstallningar", "aktiverad", varde)
			boot = frappe._dict()
			extend_bootinfo(boot)
			self.assertEqual(boot.frakt_aktiverad, bool(varde))


class TestFraktinstallningarArtikel(IntegrationTestCase):
	def setUp(self):
		from erpnext_sverige_frakt.tests.frakt_utils import aktivera_frakt

		self.inst = aktivera_frakt()

	def tearDown(self):
		frappe.db.rollback()

	def test_fraktartikel_kravs_nar_aktiverad(self):
		self.inst.fraktartikel = None
		self.assertRaises(frappe.ValidationError, self.inst.save)

	def test_lagerford_fraktartikel_vagras(self):
		from erpnext_sverige_frakt.tests.frakt_utils import make_frakt_item

		artikel = make_frakt_item("_Test Lagerford frakt", is_stock_item=1, se_goods_or_service="Vara")
		self.inst.fraktartikel = artikel
		self.assertRaises(frappe.ValidationError, self.inst.save)

	def test_fraktartikel_maste_vara_vara(self):
		from erpnext_sverige_frakt.tests.frakt_utils import make_frakt_item

		artikel = make_frakt_item("_Test Tjanst frakt", se_goods_or_service="Tjänst")
		self.inst.fraktartikel = artikel
		self.assertRaises(frappe.ValidationError, self.inst.save)
