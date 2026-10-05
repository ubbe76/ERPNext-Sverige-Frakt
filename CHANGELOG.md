# Ändringslogg

## v0.1.0 – 2026-10-05 (pre-release)

Första versionen som egen app. Frakten låg tidigare i [ERPNext Sverige](https://github.com/ubbe76/ERPNext-Sverige)
(till och med 0.2.0) och flyttades hit utan ändrad funktion:

- Transportbokning via Sendify byggd på ERPNext:s Shipment: priser, bokning med upphämtning, fraktsedel och
  etikett som PDF, spårning varje timme och avbokning.
- Kollin från artikelns mått eller förpackningstyp, upphämtningstider per veckodag och frakt på kundfakturan.
- Fraktartikeln anmäls till ERPNext Sveriges kontoval (konto 3520) med hooken `erpnext_sverige_fraktartiklar`.
- Vid installation tas modulen Frakt, menyn och ikonen över från ERPNext Sverige; data och inställningar ligger
  kvar.

Nytt i den här versionen:

- **Telefonnummer till avsändare och mottagare**, som Sendify kräver: fältet Telefon i Fraktinställningar
  (hämtas från avsändarkontakten och krävs när frakten är aktiverad) och Mottagarens telefon på försändelsen.
  Saknas ett nummer stoppas anropet innan något skickas, med ett meddelande om vilket fält som ska fyllas i.
- **Logotyp och skrivbordsikon** i appens gröna färger.
