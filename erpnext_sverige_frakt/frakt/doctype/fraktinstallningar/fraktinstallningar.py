import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_sverige_frakt.frakt import hamta_installningar, leverantor, visa_fraktfel


class Fraktinstallningar(Document):
	def validate(self):
		self.validera_upphamtningstider()
		if not self.aktiverad:
			return
		saknas = [
			self.meta.get_label(falt)
			for falt in ("bolag", "avsandaradress", "fraktartikel", "upphamtningstider")
			if not self.get(falt)
		]
		if not self.api_nyckel:
			saknas.append(self.meta.get_label("api_nyckel"))
		if saknas:
			frappe.throw(_("Fyll i {0} innan transportbokning aktiveras").format(", ".join(saknas)))
		self.validera_fraktartikel()

	def validera_upphamtningstider(self):
		from frappe.utils import get_time

		sedda = set()
		for rad in self.upphamtningstider:
			if rad.veckodag in sedda:
				frappe.throw(_("{0} finns flera gånger i Upphämtningstider").format(_(rad.veckodag)))
			sedda.add(rad.veckodag)
			if get_time(rad.fran) >= get_time(rad.till):
				frappe.throw(_("Upphämtning {0}: Från måste vara före Till").format(_(rad.veckodag).lower()))

	def validera_fraktartikel(self):
		from erpnext_sverige.setup.custom_fields import GOODS

		lagerford, typ = frappe.db.get_value(
			"Item", self.fraktartikel, ["is_stock_item", "se_goods_or_service"]
		)
		if lagerford:
			frappe.throw(_("Fraktartikeln {0} får inte vara en lagerförd artikel").format(self.fraktartikel))
		if typ != GOODS:
			frappe.throw(
				_("Fraktartikeln {0} måste ha Vara eller tjänst (moms) satt till Vara").format(
					self.fraktartikel
				)
			)


@frappe.whitelist()
@visa_fraktfel
def testa_anslutning() -> str:
	frappe.only_for(("System Manager", "Stock Manager"))
	return leverantor().kontrollera_nyckel(hamta_installningar())


@frappe.whitelist()
@visa_fraktfel
def hamta_transportorsprodukter() -> int:
	"""Prisförfrågan på en exempelsändning (en EUR-pall från avsändaren till sig själv) för att fylla registret."""
	from erpnext_sverige_frakt.frakt.fraktpris import priser_for_tillfallig_sandning
	from erpnext_sverige_frakt.frakt.parter import avsandare, forsta_upphamtning

	frappe.only_for(("System Manager", "Stock Manager"))
	inst = hamta_installningar()
	part = avsandare(inst)
	sandning = {
		"avsandare": part,
		"mottagare": part,
		"kollin": [
			{
				"kollityp": "Pall",
				"langd_cm": 120,
				"bredd_cm": 80,
				"hojd_cm": 100,
				"vikt_kg": 200,
				"antal": 1,
				"stapelbar": 0,
				"flakmeter": 0,
				"beskrivning": _("Exempelsändning"),
			},
		],
		"referens_id": "ERPNext exempelsändning",
	}
	svar = priser_for_tillfallig_sandning(sandning, forsta_upphamtning(inst))
	return len(svar["priser"])
