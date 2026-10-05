const FRAKT_INST = "erpnext_sverige_frakt.frakt.doctype.fraktinstallningar.fraktinstallningar";

frappe.ui.form.on("Fraktinstallningar", {
	refresh(frm) {
		if (!frm.doc.aktiverad) return;
		frm.add_custom_button(__("Testa anslutning"), () =>
			frappe
				.call({ method: `${FRAKT_INST}.testa_anslutning`, freeze: true })
				.then(({ message }) =>
					frappe.msgprint({
						title: __("Anslutningen fungerar"),
						indicator: "green",
						message: __("Sendify-team: {0}", [frappe.utils.escape_html(message)]),
					})
				)
		);
		frm.add_custom_button(__("Hämta transportörsprodukter"), () =>
			frappe
				.call({ method: `${FRAKT_INST}.hamta_transportorsprodukter`, freeze: true })
				.then(({ message }) =>
					frappe.msgprint(
						__("{0} transportörsprodukter finns nu i registret Fraktprodukt", [
							message,
						])
					)
				)
		);
	},
});
