"""Upphämtningstider per veckodag, stängda dagar och röda dagar i bolagets helglista."""

from datetime import date, time

import frappe
from erpnext_sverige.tests.utils import COMPANY
from frappe.tests import IntegrationTestCase

from erpnext_sverige_frakt.frakt import parter
from erpnext_sverige_frakt.patches import upphamtningstider_per_dag
from erpnext_sverige_frakt.tests.frakt_utils import aktivera_frakt

VARDAGAR = ("Måndag", "Tisdag", "Onsdag", "Torsdag")


def helglista(namn, start, slut, dagar):
	"""dagar: (datum, veckohelg)"""
	if frappe.db.exists("Holiday List", namn):
		frappe.delete_doc("Holiday List", namn, force=True)
	return (
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": namn,
				"from_date": start,
				"to_date": slut,
				"holidays": [
					{"holiday_date": d, "description": "Test", "weekly_off": int(veckohelg)}
					for d, veckohelg in dagar
				],
			}
		)
		.insert()
		.name
	)


class TestUpphamtningstider(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		aktivera_frakt()

	def setUp(self):
		frappe.db.savepoint("upphamtning_test")
		self.satt_tider(
			[(d, "09:00:00", "16:00:00") for d in VARDAGAR] + [("Fredag", "09:00:00", "14:00:00")]
		)
		# Julafton är röd dag; lördag 3 oktober är vanlig veckohelg i listan
		lista = helglista(
			"_Test Frakt helger", "2026-01-01", "2026-12-31", [("2026-12-24", False), ("2026-10-03", True)]
		)
		frappe.db.set_value("Company", COMPANY, "default_holiday_list", lista)

	def tearDown(self):
		frappe.db.rollback(save_point="upphamtning_test")

	def satt_tider(self, rader):
		inst = frappe.get_doc("Fraktinstallningar")
		inst.set("upphamtningstider", [{"veckodag": d, "fran": f, "till": t} for d, f, t in rader])
		inst.save()
		return inst

	def inst(self):
		return frappe.get_doc("Fraktinstallningar")

	def test_fredag_har_egna_tider(self):
		self.assertEqual(parter.upphamtningstider(self.inst(), date(2026, 10, 2)), (time(9), time(14)))
		self.assertEqual(parter.upphamtningstider(self.inst(), date(2026, 10, 1)), (time(9), time(16)))

	def test_dag_utan_rad_ar_stangd(self):
		self.assertIsNone(parter.upphamtningstider(self.inst(), date(2026, 10, 3)))

	def test_nasta_dag_hoppar_over_stangda_dagar(self):
		self.assertEqual(parter.nasta_upphamtningsdag(self.inst(), date(2026, 10, 1)), date(2026, 10, 2))
		self.assertEqual(parter.nasta_upphamtningsdag(self.inst(), date(2026, 10, 2)), date(2026, 10, 5))

	def test_lordag_med_rad_trots_veckohelg_i_helglistan(self):
		inst = self.satt_tider([("Fredag", "09:00:00", "14:00:00"), ("Lördag", "10:00:00", "12:00:00")])
		self.assertEqual(parter.nasta_upphamtningsdag(inst, date(2026, 10, 2)), date(2026, 10, 3))

	def test_rod_dag_hoppas_over(self):
		self.assertIsNone(parter.upphamtningstider(self.inst(), date(2026, 12, 24)))
		self.assertEqual(parter.nasta_upphamtningsdag(self.inst(), date(2026, 12, 23)), date(2026, 12, 25))

	def test_forsta_dag_fran_och_med(self):
		# Leveransdatum på en lördag: första upphämtningsdagen är måndagen efter
		self.assertEqual(parter.forsta_upphamtningsdag(self.inst(), date(2026, 10, 3)), date(2026, 10, 5))
		self.assertEqual(parter.forsta_upphamtningsdag(self.inst(), date(2026, 10, 2)), date(2026, 10, 2))

	def test_helglistetilldelning_for_datumet(self):
		if not frappe.db.exists("DocType", "Holiday List Assignment"):
			self.skipTest("Holiday List Assignment finns bara med HRMS")
		lista = helglista("_Test Frakt helger 2027", "2027-01-01", "2027-12-31", [("2027-01-06", False)])
		frappe.get_doc(
			{
				"doctype": "Holiday List Assignment",
				"applicable_for": "Company",
				"assigned_to": COMPANY,
				"holiday_list": lista,
				"from_date": "2027-01-01",
			}
		).submit()
		self.assertIsNone(parter.upphamtningstider(self.inst(), date(2027, 1, 6)))
		self.assertIsNotNone(parter.upphamtningstider(self.inst(), date(2027, 1, 7)))

	def test_ingen_upphamtningsdag_alls(self):
		inst = self.inst()
		inst.set("upphamtningstider", [])
		self.assertRaisesRegex(frappe.ValidationError, "upphämtning", parter.nasta_upphamtningsdag, inst)

	def test_dubbla_dagar_stoppas(self):
		self.assertRaisesRegex(
			frappe.ValidationError,
			"Fredag",
			self.satt_tider,
			[("Fredag", "09:00:00", "14:00:00"), ("Fredag", "10:00:00", "12:00:00")],
		)

	def test_fran_maste_vara_fore_till(self):
		self.assertRaisesRegex(
			frappe.ValidationError, "före", self.satt_tider, [("Måndag", "16:00:00", "09:00:00")]
		)

	def test_aktiverad_kraver_tider(self):
		self.assertRaisesRegex(frappe.ValidationError, "Upphämtningstider", self.satt_tider, [])

	def test_hamta_tider_for_formularet(self):
		self.assertEqual(
			parter.hamta_upphamtningstider("2026-10-02"), {"fran": "09:00:00", "till": "14:00:00"}
		)
		self.assertIn("stangt", parter.hamta_upphamtningstider("2026-12-24"))

	def test_kontroll_vid_bokning(self):
		self.assertRaisesRegex(
			frappe.ValidationError,
			"Ingen upphämtning",
			parter.kontrollera_upphamtningsdag,
			self.inst(),
			"2026-10-03",
		)
		parter.kontrollera_upphamtningsdag(self.inst(), "2026-10-02")

	def test_patchen_flyttar_gamla_tider(self):
		frappe.db.delete("Upphamtningstid", {"parent": "Fraktinstallningar"})
		for falt, varde in (("upphamtning_fran", "08:00:00"), ("upphamtning_till", "15:00:00")):
			frappe.db.delete("Singles", {"doctype": "Fraktinstallningar", "field": falt})
			frappe.db.sql(
				"insert into `tabSingles` (doctype, field, value) values ('Fraktinstallningar', %s, %s)",
				(falt, varde),
			)
		frappe.clear_document_cache("Fraktinstallningar", "Fraktinstallningar")
		upphamtningstider_per_dag.execute()
		rader = [(r.veckodag, str(r.fran), str(r.till)) for r in self.inst().upphamtningstider]
		self.assertEqual(rader, [(d, "8:00:00", "15:00:00") for d in (*VARDAGAR, "Fredag")])
