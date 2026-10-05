app_name = "erpnext_sverige_frakt"
app_title = "ERPNext Sverige Frakt"
app_publisher = "Urban Källefors"
app_description = "Freight booking via Sendify for ERPNext Sverige"
app_email = "erpnext@kallefors.se"
app_license = "gpl-3.0"

required_apps = ["erpnext_sverige"]

doctype_js = {
	"Shipment": ["public/js/frakt_prisdialog.js", "public/js/frakt_shipment.js"],
	"Delivery Note": ["public/js/frakt_forsaljning.js"],
	"Quotation": ["public/js/frakt_prisdialog.js", "public/js/frakt_forsaljning.js"],
	"Sales Order": ["public/js/frakt_prisdialog.js", "public/js/frakt_forsaljning.js"],
}

before_install = "erpnext_sverige_frakt.install.before_install"
after_install = "erpnext_sverige_frakt.install.after_install"
after_migrate = "erpnext_sverige_frakt.install.after_install"

extend_bootinfo = "erpnext_sverige_frakt.frakt.boot.extend_bootinfo"

doc_events = {
	"Item": {
		"validate": "erpnext_sverige_frakt.frakt.kollin.validera_artikel",
	},
	"Sales Invoice": {
		"before_insert": "erpnext_sverige_frakt.frakt.fraktpris.lagg_frakt_pa_faktura",
	},
	"Shipment": {
		"before_cancel": "erpnext_sverige_frakt.frakt.bokning.avboka_vid_avbrott",
		"on_trash": "erpnext_sverige_frakt.frakt.bokning.radera_vid_borttagning",
	},
}

scheduler_events = {
	"hourly": ["erpnext_sverige_frakt.frakt.sparning.uppdatera_alla"],
}

# Bokföringen i ERPNext Sverige bokför fraktartikeln på konto 3520
erpnext_sverige_fraktartiklar = ["erpnext_sverige_frakt.frakt.artikel.fraktartiklar"]

before_tests = "erpnext_sverige.tests.utils.before_tests"
