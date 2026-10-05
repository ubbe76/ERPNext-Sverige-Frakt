from frappe.model.document import Document


class Fraktprodukt(Document):
	def autoname(self):
		self.name = f"{self.transportor} – {self.produkt}"
