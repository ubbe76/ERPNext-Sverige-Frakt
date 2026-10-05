"""Transportbokning (modul Frakt). Leverantörsspecifik kod finns i sendify.py."""

import functools

import frappe
from frappe import _


class FraktFel(Exception):
	"""Fel från fraktleverantören, med fältfel översatta till svenska."""

	def __init__(self, meddelande, falt_fel=None, request_id=None):
		super().__init__(meddelande)
		self.meddelande = meddelande
		self.falt_fel = falt_fel or []
		self.request_id = request_id

	def som_html(self) -> str:
		rader = [frappe.utils.escape_html(self.meddelande)]
		if self.falt_fel:
			rader.append(
				"<ul>" + "".join(f"<li>{frappe.utils.escape_html(f)}</li>" for f in self.falt_fel) + "</ul>"
			)
		if self.request_id:
			rader.append(_("Referens hos Sendify: {0}").format(frappe.utils.escape_html(self.request_id)))
		return "<br>".join(rader)


def hamta_installningar():
	inst = frappe.get_cached_doc("Fraktinstallningar")
	if not inst.aktiverad:
		frappe.throw(
			_("Transportbokning är inte aktiverad. Aktivera den i {0}.").format(
				frappe.utils.get_link_to_form(
					"Fraktinstallningar", "Fraktinstallningar", _("Fraktinställningar")
				)
			)
		)
	return inst


def leverantor():
	"""Modulen för vald leverantör. Bara Sendify finns i etapp 1."""
	from erpnext_sverige_frakt.frakt import sendify

	return sendify


def visa_fraktfel(funktion):
	@functools.wraps(funktion)
	def omslag(*args, **kwargs):
		try:
			return funktion(*args, **kwargs)
		except FraktFel as fel:
			frappe.throw(fel.som_html(), title=_("Sendify"))

	return omslag
