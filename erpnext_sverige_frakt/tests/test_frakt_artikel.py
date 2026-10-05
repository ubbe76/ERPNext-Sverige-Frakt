import frappe
from erpnext_sverige.tests.utils import COMPANY, account, ensure_test_company
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt.artikel import FRAKTARTIKEL, sakerstall_fraktartikel
from erpnext_sverige_frakt.patches.skapa_fraktartikel import execute


class TestFraktartikel(IntegrationTestCase):
	def setUp(self):
		ensure_test_company()

	def tearDown(self):
		frappe.db.rollback()

	def test_patchen_skapar_artikeln_och_satter_installningen(self):
		if frappe.db.exists("Item", FRAKTARTIKEL):
			frappe.delete_doc("Item", FRAKTARTIKEL, force=True)
		frappe.db.set_single_value("Fraktinstallningar", "fraktartikel", None)
		execute()
		item = frappe.get_doc("Item", FRAKTARTIKEL)
		self.assertEqual(
			(item.item_name, item.stock_uom, item.is_stock_item, item.is_sales_item, item.is_purchase_item),
			("Frakt", frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos", 0, 1, 0),
		)
		self.assertEqual(item.se_goods_or_service, "Vara")
		self.assertEqual(
			{d.company: d.income_account for d in item.item_defaults}.get(COMPANY), account("3520")
		)
		self.assertEqual(frappe.db.get_single_value("Fraktinstallningar", "fraktartikel"), FRAKTARTIKEL)

	def test_artikeln_far_lagerinstallningarnas_standardenhet(self):
		# Siter med svenska enhetsnamn saknar "Nos" (t.ex. "Styck"); standardenheten ska användas
		if frappe.db.exists("Item", FRAKTARTIKEL):
			frappe.delete_doc("Item", FRAKTARTIKEL, force=True)
		tidigare = frappe.db.get_single_value("Stock Settings", "stock_uom")
		self.addCleanup(frappe.db.commit)
		self.addCleanup(frappe.delete_doc, "Item", FRAKTARTIKEL, force=True)
		self.addCleanup(frappe.db.set_value, "UOM", "Nos", "enabled", 1)
		self.addCleanup(frappe.db.set_single_value, "Stock Settings", "stock_uom", tidigare)
		frappe.db.set_single_value("Stock Settings", "stock_uom", "Box")
		frappe.db.set_value("UOM", "Nos", "enabled", 0)
		execute()
		self.assertEqual(frappe.db.get_value("Item", FRAKTARTIKEL, "stock_uom"), "Box")

	def test_patchen_ar_idempotent_och_behaller_vald_artikel(self):
		execute()
		execute()
		item = frappe.get_doc("Item", FRAKTARTIKEL)
		self.assertEqual(len([d for d in item.item_defaults if d.company == COMPANY]), 1)
		frappe.db.set_single_value("Fraktinstallningar", "fraktartikel", "_Annan")
		execute()
		self.assertEqual(frappe.db.get_single_value("Fraktinstallningar", "fraktartikel"), "_Annan")

	def test_ogiltig_befintlig_fraktartikel_pekas_inte_ut(self):
		execute()
		frappe.db.set_value("Item", FRAKTARTIKEL, "se_goods_or_service", "Tjänst")
		frappe.db.set_single_value("Fraktinstallningar", "fraktartikel", None)
		sakerstall_fraktartikel()
		self.assertFalse(frappe.db.get_single_value("Fraktinstallningar", "fraktartikel"))

	def test_rad_utan_intaktskonto_far_fraktkontot(self):
		# ERPNext lägger till en rad för standardbolaget utan intäktskonto när artikeln skapas efter guiden
		execute()
		item = frappe.get_doc("Item", FRAKTARTIKEL)
		for rad in item.item_defaults:
			if rad.company == COMPANY:
				rad.income_account = None
		item.save()
		sakerstall_fraktartikel()
		self.assertEqual(
			frappe.db.get_value(
				"Item Default", {"parent": FRAKTARTIKEL, "company": COMPANY}, "income_account"
			),
			account("3520"),
		)
