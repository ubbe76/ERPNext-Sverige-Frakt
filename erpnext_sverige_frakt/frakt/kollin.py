"""Kolliförslag från artikelrader (egna mått eller förpackningstyp)."""

import math

import frappe
from erpnext.stock.doctype.item.item import get_uom_conv_factor
from frappe import _
from frappe.utils import flt

EGNA_MATT = "Egna mått"
FORPACKNING = "Förpackning"
PALLPLATS_FLAKMETER = 0.4


def validera_artikel(doc, method=None):
	"""Item.validate: pallplatser → flakmeter, och förpackning kräver typ och antal."""
	if doc.fraktsatt == EGNA_MATT and flt(doc.frakt_pallplatser) and not flt(doc.frakt_flakmeter):
		doc.frakt_flakmeter = flt(doc.frakt_pallplatser) * PALLPLATS_FLAKMETER
	if doc.fraktsatt == FORPACKNING and (not doc.forpackningstyp or flt(doc.antal_per_forpackning) <= 0):
		frappe.throw(_("Ange förpackningstyp och antal per förpackning (större än noll)"))


OVRIGT = "Övrigt"


def vikt_kg(item) -> float:
	"""Artikelns vikt per lagerenhet i kg. Saknas viktenhet räknas vikten som kg."""
	vikt = flt(item.weight_per_unit)
	if not vikt or not item.weight_uom:
		return vikt
	return vikt * flt(get_uom_conv_factor(item.weight_uom, "Kg"))


def foresla_kollin(rader):
	"""rader: [(item_code, lagerantal)] → (kollin, varningar). Se modulens docstring för kollits nycklar."""
	kollin, varningar = [], []
	forpackningar = {}  # förpackningstyp → {"fyllnad", "vikt", "namn"}
	lost_vikt = 0.0  # vikt från artiklar utan fraktsätt

	for item_code, antal in rader:
		antal = flt(antal)
		if antal <= 0:
			continue
		item = frappe.get_cached_doc("Item", item_code)
		vikt = vikt_kg(item)
		if not vikt:
			varningar.append(_("{0} saknar vikt").format(item.item_name))

		if item.fraktsatt == EGNA_MATT:
			if not (flt(item.frakt_langd_cm) and flt(item.frakt_bredd_cm) and flt(item.frakt_hojd_cm)):
				varningar.append(_("{0} saknar mått").format(item.item_name))
			kollin.append(
				{
					"kollityp": item.frakt_kollityp or "Paket",
					"langd_cm": flt(item.frakt_langd_cm),
					"bredd_cm": flt(item.frakt_bredd_cm),
					"hojd_cm": flt(item.frakt_hojd_cm),
					"vikt_kg": round(vikt, 2),
					"antal": math.ceil(antal),
					"stapelbar": int(item.frakt_stapelbar or 0),
					"flakmeter": flt(item.frakt_flakmeter),
					"beskrivning": item.item_name[:100],
				}
			)
		elif item.fraktsatt == FORPACKNING and item.forpackningstyp and flt(item.antal_per_forpackning) > 0:
			f = forpackningar.setdefault(item.forpackningstyp, {"fyllnad": 0.0, "vikt": 0.0, "namn": []})
			f["fyllnad"] += antal / flt(item.antal_per_forpackning)
			f["vikt"] += vikt * antal
			f["namn"].append(item.item_name)
		else:
			varningar.append(_("{0} saknar fraktsätt").format(item.item_name))
			lost_vikt += vikt * antal

	forpackningskollin = []
	for typ, f in forpackningar.items():
		forp = frappe.get_cached_doc("Forpackningstyp", typ)
		antal = max(1, math.ceil(round(f["fyllnad"], 6)))
		forpackningskollin.append(
			{
				"kollityp": forp.kollityp,
				"langd_cm": flt(forp.langd_cm),
				"bredd_cm": flt(forp.bredd_cm),
				"hojd_cm": flt(forp.hojd_cm),
				"vikt_kg": flt(forp.egenvikt_kg) + f["vikt"] / antal,
				"antal": antal,
				"stapelbar": int(forp.stapelbar or 0),
				"flakmeter": flt(forp.flakmeter),
				"beskrivning": ", ".join(dict.fromkeys(f["namn"]))[:100],
			}
		)

	if lost_vikt and forpackningskollin:
		per_enhet = lost_vikt / sum(k["antal"] for k in forpackningskollin)
		for k in forpackningskollin:
			k["vikt_kg"] += per_enhet
	elif lost_vikt:
		kollin.append(
			{
				"kollityp": OVRIGT,
				"langd_cm": 0,
				"bredd_cm": 0,
				"hojd_cm": 0,
				"vikt_kg": round(lost_vikt, 2),
				"antal": 1,
				"stapelbar": 0,
				"flakmeter": 0,
				"beskrivning": _("Övrigt"),
			}
		)

	for k in forpackningskollin:
		k["vikt_kg"] = round(k["vikt_kg"], 2)
	return kollin + forpackningskollin, varningar
