"""Skapar fraktartikeln "Frakt" och pekar ut den i Fraktinställningar (ersätter fraktkontot)."""

from erpnext_sverige.setup.custom_fields import create_custom_fields

from erpnext_sverige_frakt.install import after_install


def execute():
	# after_migrate (som skapar custom fields) körs efter patcharna, men artikeln behöver ERPNext Sveriges
	# fält se_goods_or_service och fraktens egna fält.
	create_custom_fields()
	after_install()
