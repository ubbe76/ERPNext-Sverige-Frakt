// Gemensam prisdialog för Shipment, offert och försäljningsorder.
window.erpnext_sverige_frakt = {
	format_dagar(p) {
		if (p.dagar_min == null) return "";
		return p.dagar_min === p.dagar_max ? `${p.dagar_min}` : `${p.dagar_min}–${p.dagar_max}`;
	},

	visa_priser(svar, alternativ) {
		const priser = svar.priser || [];
		const esc = frappe.utils.escape_html;
		const rader = priser
			.map(
				(p, i) => `
			<tr data-index="${i}" class="${p.forvald ? "table-active" : ""}" style="cursor:pointer">
				<td><input type="radio" name="frakt_pris" value="${i}" ${p.forvald ? "checked" : ""}></td>
				<td>${esc(p.transportor)}${
					p.forvald ? ` <span class="indicator-pill blue">${__("Förval")}</span>` : ""
				}</td>
				<td>${esc(p.produkt)}</td>
				<td class="text-right">${format_currency(p.pris, p.valuta)}</td>
				<td class="text-right">${format_currency(p.kundpris, p.valuta)}</td>
				<td class="text-center">${this.format_dagar(p)}</td>
				<td>${esc((p.upphamtning && p.upphamtning.date) || "")}</td>
				<td>${esc((p.leverans && p.leverans.earliest_date) || "")}</td>
			</tr>`
			)
			.join("");
		const varningar = (svar.varningar || []).length
			? `<div class="alert alert-warning mt-3"><b>${__(
					"Transportörer som inte kunde erbjudas"
			  )}</b><ul>${svar.varningar.map((v) => `<li>${esc(v)}</li>`).join("")}</ul></div>`
			: "";
		const tabell = priser.length
			? `<table class="table table-bordered table-hover">
				<thead><tr><th></th><th>${__("Transportör")}</th><th>${__("Produkt")}</th>
				<th class="text-right">${__("Pris")}</th><th class="text-right">${__("Kundpris")}</th>
				<th class="text-center">${__("Dagar")}</th><th>${__("Upphämtning")}</th><th>${__(
					"Leverans"
			  )}</th></tr></thead>
				<tbody>${rader}</tbody></table>`
			: `<p>${__("Inga priser hittades.")}</p>`;

		const valt = () => {
			const v = dialog.$wrapper.find("input[name=frakt_pris]:checked").val();
			if (v === undefined) {
				frappe.msgprint(__("Välj ett alternativ"));
				return null;
			}
			return priser[cint(v)];
		};
		const dialog = new frappe.ui.Dialog({
			title: alternativ.title || __("Fraktpriser"),
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "priser", options: tabell + varningar }],
			primary_action_label: alternativ.primar.label,
			primary_action: () => {
				const p = valt();
				if (!p) return;
				if (p.giltig_till && new Date(p.giltig_till) < new Date()) {
					frappe.msgprint(__("Priset har gått ut. Hämta priser igen."));
					dialog.hide();
					return;
				}
				dialog.hide();
				alternativ.primar.action(p);
			},
			secondary_action_label: alternativ.sekundar ? alternativ.sekundar.label : __("Stäng"),
			secondary_action: () => {
				if (!alternativ.sekundar) return dialog.hide();
				const p = valt();
				if (!p) return;
				dialog.hide();
				alternativ.sekundar.action(p);
			},
		});
		dialog.$wrapper.on("click", "tr[data-index]", function () {
			$(this).find("input[name=frakt_pris]").prop("checked", true);
		});
		dialog.show();
		return dialog;
	},
};
