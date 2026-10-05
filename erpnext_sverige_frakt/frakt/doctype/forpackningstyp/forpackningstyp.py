import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class Forpackningstyp(Document):
	def validate(self):
		for falt in ("langd_cm", "bredd_cm", "hojd_cm"):
			if flt(self.get(falt)) <= 0:
				frappe.throw(_("{0} måste vara större än noll").format(self.meta.get_label(falt)))
		if flt(self.egenvikt_kg) < 0:
			frappe.throw(_("Egenvikten kan inte vara negativ"))
