# ERPNext Sverige Frakt

> [!IMPORTANT]
> **Under utveckling.** Appen har automatiska tester men är ännu inte provad skarpt mot transportör, bara mot
> Sendifys sandlåda. Prova på en testsite först.

Transportbokning via [Sendify](https://www.sendify.se) för [ERPNext](https://github.com/frappe/erpnext) version 16.
Appen bygger på [ERPNext Sverige](https://github.com/ubbe76/ERPNext-Sverige), som måste vara installerad.

## Vad appen gör

Transportbokning via [Sendify](https://www.sendify.se), som förmedlar bland annat DHL, UPS, DSV, PostNord och
Schenker. Modulen **Frakt** bygger på ERPNext:s Shipment (försändelse).

**Inställningar** (Fraktinställningar): miljö (Sandlåda eller Produktion), API-nyckel (skapas i Sendify under
*Settings → API*, sparas krypterad), avsändande bolag, adress och kontakt, upphämtningstider, påslag på
fraktpriset (procent och/eller kronor) och fraktartikeln. Allt finns i menyn **Frakt**.

**Upphämtningstider** anges per veckodag (Från och Till), till exempel kortare fredag. En dag utan rad har ingen
upphämtning, och röda dagar i bolagets helglista har aldrig upphämtning (vanliga veckohelger räknas inte, så en
lördagsrad fungerar). En ny försändelse får nästa dag med upphämtning och den dagens tider. Ändras dagen på
försändelsen byts tiderna, och en dag utan upphämtning stoppar prishämtning och bokning. **Testa anslutning** kontrollerar nyckeln och
**Hämta transportörsprodukter** fyller registret Fraktprodukt. Frakten används först när **Aktiverad** är ikryssad.

**Kollin**: på artikeln anges fraktsätt, antingen egna mått (längd, bredd, höjd, eventuellt pallplatser som räknas
om till flakmeter) eller en förpackningstyp (t.ex. EUR-pall) med antal per förpackning. Utifrån det föreslås kollin.

**Boka**:

1. På en godkänd följesedel skapar **Skapa → Boka transport** en försändelse med föreslagna kollin, som går att
   ändra (**Föreslå kollin igen** gör ett nytt förslag).
2. **Hämta priser** visar alla transportörers priser och kundpris. Välj och **Boka**, eller **Spara val** och boka
   senare. En kund kan ha en förvald fraktprodukt som bokas direkt med **Boka med förval**.
3. Vid bokning beställs alltid upphämtning. Transportör och fraktsedelsnummer skrivs på följesedeln, och
   fraktsedel och etikett sparas som PDF-bilagor på försändelsen (**Hämta fraktsedel** hämtar dem igen).
4. Har priset ändrats mer än **Bekräfta prisändring över (%)** (standard 5 %) sedan valet sparades måste
   ändringen bekräftas. Ett utgånget pris måste hämtas igen.

Avbryts försändelsen i ERPNext avbokas den hos Sendify.

**Spårning** hämtas varje timme för bokade försändelser och visas på försändelsen (**Uppdatera spårning**,
**Öppna spårning**). Vid leverans blir försändelsen *Completed*, och avvikelser hos transportören visas.

**Frakt på fakturan**: när en kundfaktura skapas från en följesedel med bokad försändelse läggs frakten till som
en rad med fraktartikeln (kundpris = Sendifys pris plus påslag). Raden går att ändra. På offert och
försäljningsorder hämtar **Kontrollera fraktpris** priser utan att boka, och **Lägg till frakt** lägger frakten på
ordern, som då inte faktureras igen från försändelsen.

I sandlådan fungerar fullständig bokning bara med DHL, UPS och DSV, och spårningen ger bara händelsen `ORDERED`.
Ombud, tull, egen inlämning och flera Sendify-konton stöds inte än.

Fraktartikeln bokförs på konto 3520 (Fakturerade frakter) för svenska kunder genom ERPNext Sveriges automatiska
kontoval; appen anmäler den med hooken `erpnext_sverige_fraktartiklar`.

## Installation

Krav: en [bench](https://github.com/frappe/bench) med `frappe`, `erpnext` och `erpnext_sverige` (0.3.0 eller senare)
på branchen `version-16`.

```bash
bench get-app https://github.com/ubbe76/ERPNext-Sverige-Frakt --branch version-16
bench --site <site> install-app erpnext_sverige_frakt
bench --site <site> clear-cache
```

### Uppgradering från ERPNext Sverige 0.2 eller tidigare

Frakten låg tidigare i ERPNext Sverige. Data och inställningar ligger kvar, men **installera fraktappen innan
siten migreras**, annars tar `migrate` bort fraktens doctyper som föräldralösa (tabellerna finns kvar, men fältet
med spårningshändelser på försändelsen försvinner):

```bash
bench --site <site> backup
bench get-app https://github.com/ubbe76/ERPNext-Sverige-Frakt --branch version-16
cd apps/erpnext_sverige && git pull && cd ../..        # 0.3.0, utan frakt
bench --site <site> install-app erpnext_sverige_frakt   # före migrate
bench --site <site> migrate
bench build --app erpnext_sverige_frakt
```

## Tester

```bash
bench --site <testsite> run-tests --app erpnext_sverige_frakt
```

Testerna använder testbolaget från ERPNext Sverige. `test_frakt_sandlada` anropar Sendifys sandlåda och körs bara
när en sandlådenyckel finns.

## Licens

GPL-3.0
