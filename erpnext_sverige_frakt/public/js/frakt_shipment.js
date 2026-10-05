// Knappar för transportbokning på Shipment.
const FRAKT_BOKNING = "erpnext_sverige_frakt.frakt.bokning";

frappe.ui.form.on("Shipment", {
	// Upphämtningstiderna följer dagen enligt Fraktinställningar; stängda och röda dagar ger en varning
	pickup_date(frm) {
		if (!frappe.boot.frakt_aktiverad || !frm.doc.pickup_date || frm.doc.docstatus !== 0)
			return;
		frappe
			.call({
				method: "erpnext_sverige_frakt.frakt.parter.hamta_upphamtningstider",
				args: { datum: frm.doc.pickup_date },
			})
			.then((r) => {
				const svar = r.message || {};
				if (svar.stangt) {
					frappe.msgprint({ message: svar.stangt, indicator: "orange" });
					return;
				}
				frm.set_value({ pickup_from: svar.fran, pickup_to: svar.till });
			});
	},

	refresh(frm) {
		if (!frappe.boot.frakt_aktiverad || frm.is_new()) return;
		const grupp = __("Sendify");
		const frakt = window.erpnext_sverige_frakt;

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("Föreslå kollin igen"),
				() =>
					frappe.confirm(
						__("Kollitabellen ersätts med ett nytt förslag. Fortsätta?"),
						() =>
							frappe
								.call({
									method: `${FRAKT_BOKNING}.foresla_kollin_igen`,
									args: { shipment: frm.doc.name },
									freeze: true,
								})
								.then(() => frm.reload_doc())
					),
				grupp
			);

			frm.add_custom_button(
				__("Hämta priser"),
				() => spara_forst(frm).then(() => hamta_priser(frm)),
				grupp
			);

			if (frm.doc.fraktprodukt) {
				const label = frm.doc.fraktpris ? __("Boka vald produkt") : __("Boka med förval");
				frm.add_custom_button(
					label,
					() => spara_forst(frm).then(() => boka_vald(frm, 0)),
					grupp
				);
			}
		}

		if (["Booked", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Hämta fraktsedel"),
				() =>
					frappe
						.call({
							method: `${FRAKT_BOKNING}.hamta_dokument`,
							args: { shipment: frm.doc.name },
							freeze: true,
						})
						.then(() => frm.reload_doc()),
				grupp
			);
			frm.add_custom_button(
				__("Uppdatera spårning"),
				() =>
					frappe
						.call({
							method: "erpnext_sverige_frakt.frakt.sparning.uppdatera",
							args: { shipment: frm.doc.name },
							freeze: true,
						})
						.then(() => frm.reload_doc()),
				grupp
			);
			if (/^https?:\/\//i.test(frm.doc.tracking_url || "")) {
				frm.add_custom_button(
					__("Öppna spårning"),
					() => window.open(frm.doc.tracking_url),
					grupp
				);
			}
		}

		if (frm.doc.senaste_sparningsstatus === "EXCEPTION") {
			frm.dashboard.set_headline_alert(
				__("Avvikelse hos transportören: {0}", [
					frappe.utils.escape_html(frm.doc.senaste_sparning || ""),
				]),
				"red"
			);
		}

		function spara_forst(frm) {
			return frm.is_dirty() ? frm.save() : Promise.resolve();
		}

		function hamta_priser(frm) {
			frappe
				.call({
					method: `${FRAKT_BOKNING}.hamta_priser`,
					args: { shipment: frm.doc.name },
					freeze: true,
					freeze_message: __("Hämtar priser från Sendify …"),
				})
				.then(({ message }) => visa(frm, message));
		}

		function visa(frm, svar) {
			frakt.visa_priser(svar, {
				title: __("Fraktpriser för {0}", [frm.doc.name]),
				primar: {
					label: __("Boka"),
					action: (p) =>
						frappe
							.call({
								method: `${FRAKT_BOKNING}.boka`,
								args: {
									shipment: frm.doc.name,
									token: p.token,
									fraktprodukt: p.fraktprodukt,
									pris: p.pris,
									valuta: p.valuta,
								},
								freeze: true,
								freeze_message: __("Bokar …"),
							})
							.then(() => frm.reload_doc()),
				},
				sekundar: {
					label: __("Spara val"),
					action: (p) =>
						frappe
							.call({
								method: `${FRAKT_BOKNING}.spara_val`,
								args: {
									shipment: frm.doc.name,
									fraktprodukt: p.fraktprodukt,
									pris: p.pris,
									valuta: p.valuta,
								},
							})
							.then(() => frm.reload_doc()),
				},
			});
		}

		function boka_vald(frm, bekraftat) {
			frappe
				.call({
					method: `${FRAKT_BOKNING}.boka_vald_produkt`,
					args: { shipment: frm.doc.name, bekraftat },
					freeze: true,
					freeze_message: __("Bokar …"),
				})
				.then(({ message: svar }) => {
					if (svar.status === "bokad") return frm.reload_doc();
					if (svar.status === "prisandring") {
						return frappe.confirm(
							__("Priset har ändrats från {0} till {1}. Boka ändå?", [
								format_currency(svar.gammalt, frm.doc.fraktpris_valuta),
								format_currency(svar.nytt, frm.doc.fraktpris_valuta),
							]),
							() => boka_vald(frm, 1)
						);
					}
					frappe.show_alert({
						message: __("{0} finns inte bland alternativen just nu", [
							frm.doc.fraktprodukt,
						]),
						indicator: "orange",
					});
					visa(frm, svar);
				});
		}
	},
});
