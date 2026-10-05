// "Boka transport" på följesedel och "Kontrollera fraktpris" på offert och försäljningsorder.
// Blockscope: filen laddas för flera doctyper och ett toppnivå-const skulle deklareras om.
{
	const FRAKT_PRIS = "erpnext_sverige_frakt.frakt.fraktpris";

	frappe.ui.form.on("Delivery Note", {
		refresh(frm) {
			if (!frappe.boot.frakt_aktiverad || frm.doc.docstatus !== 1) return;
			if (frm.doc.lr_no && frappe.model.can_read("Shipment")) {
				// Spårningslänk från den bokade försändelsen
				frappe.db
					.get_list("Shipment", {
						filters: [
							["Shipment Delivery Note", "delivery_note", "=", frm.doc.name],
							["docstatus", "=", 1],
						],
						fields: ["name", "tracking_url", "senaste_sparning"],
						limit: 1,
					})
					.then(([s]) => {
						if (!s || !/^https?:\/\//i.test(s.tracking_url || "")) return;
						frm.dashboard.add_comment(
							__("Spårning {0}: {1}", [
								`<a href="${encodeURI(
									s.tracking_url
								)}" target="_blank" rel="noopener">${frappe.utils.escape_html(
									frm.doc.lr_no
								)}</a>`,
								frappe.utils.escape_html(s.senaste_sparning || ""),
							]),
							"blue",
							true
						);
					});
			}
			if (!frappe.model.can_create("Shipment")) return;
			frm.add_custom_button(
				__("Boka transport"),
				() =>
					frappe
						.call({
							method: "erpnext_sverige_frakt.frakt.bokning.skapa_shipment",
							args: { delivery_note: frm.doc.name },
							freeze: true,
						})
						.then(({ message }) => frappe.set_route("Form", "Shipment", message)),
				__("Create")
			);
		},
	});

	const erpnext_sverige_fraktpris = {
		refresh(frm) {
			if (!frappe.boot.frakt_aktiverad || frm.is_new() || frm.doc.docstatus === 2) return;
			frm.add_custom_button(__("Kontrollera fraktpris"), () => {
				frappe
					.call({
						method: `${FRAKT_PRIS}.kontrollera`,
						args: { doctype: frm.doctype, name: frm.doc.name },
						freeze: true,
						freeze_message: __("Hämtar priser från Sendify …"),
					})
					.then(({ message }) => {
						const utkast = frm.doc.docstatus === 0;
						window.erpnext_sverige_frakt.visa_priser(message, {
							title: __("Fraktpris för {0}", [frm.doc.name]),
							primar: utkast
								? {
										label: __("Lägg till frakt"),
										action: (p) =>
											frappe
												.call({
													method: `${FRAKT_PRIS}.lagg_till_frakt`,
													args: {
														doctype: frm.doctype,
														name: frm.doc.name,
														fraktprodukt: p.fraktprodukt,
														kundpris: p.kundpris,
													},
												})
												.then(() => frm.reload_doc()),
								  }
								: {
										label: __("Spara val"),
										action: (p) =>
											frappe
												.call({
													method: `${FRAKT_PRIS}.spara_val_order`,
													args: {
														doctype: frm.doctype,
														name: frm.doc.name,
														fraktprodukt: p.fraktprodukt,
													},
												})
												.then(() => frm.reload_doc()),
								  },
							sekundar: null,
						});
					});
			});
		},
	};

	frappe.ui.form.on("Quotation", erpnext_sverige_fraktpris);
	frappe.ui.form.on("Sales Order", erpnext_sverige_fraktpris);
}
