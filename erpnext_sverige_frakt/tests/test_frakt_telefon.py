"""Telefonnummer till avsändare och mottagare: Sendify kräver dem, och kontakten saknar dem ofta."""

from unittest.mock import patch

import frappe
from erpnext_sverige.tests.utils import COMPANY

from erpnext_sverige_frakt.frakt import bokning, hamta_installningar
from erpnext_sverige_frakt.frakt.parter import avsandare
from erpnext_sverige_frakt.tests.frakt_utils import make_kontakt
from erpnext_sverige_frakt.tests.test_frakt_bokning import FraktTestCase

KONTAKTENS = "0701234567"  # make_kontakt


class TestAvsandarensTelefon(FraktTestCase):
	def installningar(self, **falt):
		inst = frappe.get_doc("Fraktinstallningar")
		inst.update(falt)
		inst.save()
		return inst

	def test_fylls_i_fran_kontakten(self):
		inst = self.installningar(avsandartelefon=None)
		self.assertEqual(inst.avsandartelefon, KONTAKTENS)
		self.assertEqual(avsandare(hamta_installningar())["telefon"], KONTAKTENS)

	def test_eget_nummer_skickas(self):
		self.installningar(avsandartelefon="08-123 456")
		self.assertEqual(avsandare(hamta_installningar())["telefon"], "08-123 456")

	def test_aktiverad_frakt_utan_telefon_stoppas(self):
		utan = make_kontakt("_Test Avsändare Utan Telefon", "Company", COMPANY, telefon=None)
		with self.assertRaisesRegex(frappe.ValidationError, "Telefon"):
			self.installningar(avsandarkontakt=utan, avsandartelefon=None)


class TestMottagarensTelefon(FraktTestCase):
	def test_forsandelsen_far_kontaktens_nummer(self):
		doc, _dn = self.shipment()
		self.assertEqual(doc.mottagartelefon, KONTAKTENS)

	def test_andrat_nummer_skickas(self):
		doc, _dn = self.shipment()
		doc.mottagartelefon = "070-999 99 99"
		doc.save()
		self.assertEqual(bokning.sandning_fran_shipment(doc)["mottagare"]["telefon"], "070-999 99 99")

	def test_saknat_nummer_stoppas_innan_sendify_anropas(self):
		doc, _dn = self.shipment()
		doc.delivery_contact_name = make_kontakt(
			"_Test Mottagare Utan Telefon", "Customer", self.kund, telefon=None
		)
		doc.mottagartelefon = None
		doc.save()
		with patch("erpnext_sverige_frakt.frakt.sendify.requests.request") as anrop:
			with self.assertRaisesRegex(frappe.ValidationError, "Mottagarens telefon"):
				bokning.hamta_priser(doc.name)
		anrop.assert_not_called()
