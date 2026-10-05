"""Fraktappen som egen app: modulen Frakt, menyn och fraktartikeln till bokföringen i ERPNext Sverige."""

import os

import frappe
from erpnext_sverige.accounting.account_selection import fraktartiklar
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.install import before_install
from erpnext_sverige_frakt.tests.frakt_utils import aktivera_frakt

APP = "erpnext_sverige_frakt"


class TestInstallation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.inst = aktivera_frakt()  # sätter upp testbolaget, som committar

	def setUp(self):
		frappe.db.savepoint("frakt_installation")

	def tearDown(self):
		frappe.db.rollback(save_point="frakt_installation")

	def test_modulen_tillhor_appen(self):
		self.assertEqual(frappe.db.get_value("Module Def", "Frakt", "app_name"), APP)

	def test_before_install_tar_over_modulen_fran_erpnext_sverige(self):
		# Siter där frakten låg i ERPNext Sverige: modulposten måste bort innan installationen lägger till den
		frappe.db.set_value("Module Def", "Frakt", "app_name", "erpnext_sverige")
		before_install()
		self.assertFalse(frappe.db.exists("Module Def", "Frakt"))
		self.assertTrue(frappe.db.exists("DocType", "Fraktinstallningar"))

	def test_before_install_tar_over_meny_och_ikon(self):
		# Annars tar migrate bort dem som föräldralösa, eftersom ERPNext Sverige inte längre har filerna
		for doctype in ("Desktop Icon", "Workspace Sidebar"):
			frappe.db.set_value(doctype, "Frakt", "app", "erpnext_sverige")
		before_install()
		for doctype in ("Desktop Icon", "Workspace Sidebar"):
			self.assertEqual(frappe.db.get_value(doctype, "Frakt", "app"), APP, doctype)

	def test_before_install_lamnar_egen_modul(self):
		before_install()
		self.assertEqual(frappe.db.get_value("Module Def", "Frakt", "app_name"), APP)

	def test_fraktartikeln_anmals_till_bokforingen(self):
		self.assertIn(self.inst.fraktartikel, fraktartiklar())

	def test_ingen_fraktartikel_utan_installning(self):
		frappe.db.set_single_value("Fraktinstallningar", "fraktartikel", None)
		self.assertEqual(fraktartiklar(), set())

	def test_meny_under_erpnext(self):
		ikon = frappe.get_doc("Desktop Icon", "Frakt")
		self.assertEqual((ikon.app, ikon.parent_icon, ikon.link_type), (APP, "ERPNext", "Workspace Sidebar"))
		self.assertFalse(ikon.hidden)
		meny = frappe.get_doc("Workspace Sidebar", "Frakt")
		self.assertEqual(meny.app, APP)
		for rad in meny.items:
			if rad.type == "Link":
				self.assertTrue(frappe.db.exists(rad.link_type, rad.link_to), rad.link_to)

	def test_skrivbordsikonen_har_logotypens_farger(self):
		# Skrivbordet letar efter ikonen under ikonens app (assets/<app>/icons/desktop_icons/<variant>/frakt.svg)
		mapp = frappe.get_app_path(APP, "public", "icons", "desktop_icons")
		for variant, farg in (("solid", "#2E9E6B"), ("subtle", "#1F7A50")):
			with open(os.path.join(mapp, variant, "frakt.svg")) as f:
				self.assertIn(farg, f.read(), variant)
