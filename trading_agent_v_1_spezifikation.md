# Trading Agent V1 – Fachliche Spezifikation

## 1. Ziel des Systems

Der Trading Agent V1 soll eine bestehende, regelbasierte Strategie automatisiert erkennen, beurteilen und in einer ersten Ausbaustufe über ein Order-Modul als Pending Orders verwalten.

Die Strategie besteht aus zwei Signalarten:

1. Trend-Signale
2. Gegentrend-Signale

Beide Signalarten werden nicht isoliert behandelt, sondern im Gesamtkontext eines Marktregimes beurteilt.

Das Marktregime wird über MACD-basierte Zustände definiert.

V1-Ziel:
- Signale regelbasiert erkennen
- Entscheidungen deterministisch treffen
- Pending Orders setzen, anpassen und löschen
- Offene Trades gemäss Regeln managen
- Ausnahme: Market Close bei aggressivem Reversal von Trend zu Gegentrend

---

## 2. Marktregime

Das Regime wird über den MACD bestimmt.

### 2.1 Bullishes Regime
Bullishes Regime liegt vor, wenn:
- MACD über der 0-Linie liegt
- und MACD über der roten Signallinie liegt

### 2.2 Bearishes Regime
Bearishes Regime liegt vor, wenn:
- die inverse Konstellation zum bullishen Regime vorliegt

### 2.3 Neutrales Regime
Neutrales Regime liegt vor, wenn weder bullishes noch bearishes Regime erfüllt ist.

---

## 3. Indikator- und Referenzwerte

### 3.0 Indikator-Parameter

#### Bollinger Bands
Für die Strategie werden Bollinger Bands mit folgenden Einstellungen verwendet:
- Periode: 12
- Abweichungen: 2
- Versatz: 0
- Angewendet auf: Close

#### MACD
Für die Strategie wird der MACD mit folgenden Einstellungen verwendet:
- Fast EMA Period: 12
- Slow EMA Period: 26
- Signal SMA Period: 9

Hinweis:
Die frühere Notiz zum 4h-Chart wird nicht als feste Timeframe-Regel in die V1-Spezifikation übernommen.


### 3.1 Bollinger Bands
Alle für Entry, TP und SL relevanten Werte basieren auf den Bollinger-Bändern des zuletzt abgeschlossenen Bars zum jeweiligen Prüfzeitpunkt.

### 3.2 Relative Schwellen
Zur Definition von „deutlich innerhalb“ und „deutlich ausserhalb“ wird nicht mit fixen Pips gearbeitet, sondern mit relativen Werten.

Referenz ist die halbe Bandbreite:
- obere Hälfte: oberes Bollinger-Band minus mittleres Bollinger-Band
- untere Hälfte: mittleres Bollinger-Band minus unteres Bollinger-Band

Startparameter V1:
- inside_buffer_pct = 0.20
- outside_buffer_pct = 0.20

Interpretation:
- deutlich innerhalb = Schlusskurs hat mindestens 20 % der relevanten halben Bandbreite Abstand zum äusseren Band
- deutlich ausserhalb = Schlusskurs liegt mindestens 20 % der relevanten halben Bandbreite ausserhalb des äusseren Bandes

### 3.3 Mindestbreite der Bollinger-Struktur
Der Abstand zwischen mittlerem Bollinger-Band und relevantem äusseren Bollinger-Band darf nicht zu klein sein.

Definition:
- aktueller Abstand wird mit dem Durchschnitt der letzten 30 Bars verglichen
- Messgrösse: absolute Distanz in Pips
- Gültig nur wenn aktueller Abstand >= 70 % des 30-Bar-Durchschnitts

Diese Regel gilt für Trend- und Gegentrend-Setups.

---

## 4. Trading-Zeit

Der Agent arbeitet nicht tickbasiert, sondern zu fest definierten Prüfzeitpunkten („Trading-Zeit“).

Beispiel:
- täglich um 07:00 Uhr

Zu jedem Prüfzeitpunkt führt der Agent aus:
- neue Signale prüfen
- bestehende Pending Orders validieren
- Orders anpassen oder löschen
- offene Trades managen

---

## 5. Trend-Signal

Ein Trend-Signal kann nur entstehen, wenn ein aktives Trendregime besteht.

### 5.1 Richtung
- bullishes Regime -> potenzielles Trend-Long-Signal
- bearishes Regime -> potenzielles Trend-Short-Signal

### 5.2 Kumulative Bedingungen für Trend-Signal

Alle folgenden Bedingungen müssen erfüllt sein:

1. Der letzte abgeschlossene Bar schliesst in Trendrichtung.
   - bullish: Schlusskurs > Eröffnungskurs
   - bearish: Schlusskurs < Eröffnungskurs
   - sehr knappe Unterschiede werden ignoriert; die relative Mindestschwelle wird später technisch parametrierbar gehalten

2. Der Schlusskurs des Signal-Bars liegt deutlich innerhalb der Bollinger-Bänder.

3. Das Signal entsteht innerhalb der ersten 6 Bars seit Beginn des aktuellen Trendregimes.
   - danach ungültig

4. Im laufenden Trendregime darf noch kein früherer potenzieller Trend-Einstieg in dieselbe Richtung vorgelegen haben.
   - Sobald im aktuellen Trendregime irgendwann eine Konstellation vorlag, bei der ein Trend-Entry hätte entstehen können, ist kein weiterer Trend-Entry in derselben Richtung im selben Regime zulässig.

5. Der letzte Bar vor Entstehung des Trendregimes, also der letzte Bar im neutralen Hintergrund, muss mit seinem Schlusskurs innerhalb der Bollinger-Bänder liegen.

6. Falls in der letzten neutralen Phase vor Entstehung des Trendregimes ein Schlusskurs deutlich ausserhalb der Bollinger-Bänder entgegen der späteren Trendrichtung lag, dann muss der Kurs zuerst mindestens einmal das mittlere Bollinger-Band berührt haben, bevor ein Trend-Signal gültig ist.
   - Zur Neutralisierung genügt ein High/Low-Touch des mittleren Bollinger-Bands.
   - Nur die letzte neutrale Phase vor dem aktuellen Trendregime ist relevant.

7. Die Mindestbreite der Bollinger-Struktur gemäss Abschnitt 3.3 muss erfüllt sein.

### 5.3 Trend-Entry
Der Entry eines Trend-Signals liegt am relevanten äusseren Bollinger-Band des letzten abgeschlossenen Signal-Bars.

- bullish -> Entry am oberen äusseren Bollinger-Band
- bearish -> Entry am unteren äusseren Bollinger-Band

### 5.4 Trend-Ordertyp
Trend-Entries werden grundsätzlich als Stop-Orders gesetzt:
- bullish -> Buy Stop
- bearish -> Sell Stop

### 5.5 Trend-SL und Trend-TP
- Fachregel: Trend = 2R
- SL liegt initial auf dem mittleren Bollinger-Band des zuletzt abgeschlossenen Bars
- TP wird im Verhältnis 2:1 zum Risiko gesetzt

### 5.6 Management nicht gefillter Trend-Orders
Zu jedem Prüfzeitpunkt:
- prüfen, ob Signal weiterhin gültig ist
- falls ungültig -> Order löschen
- falls weiterhin gültig -> Entry, SL und TP auf Basis des zuletzt abgeschlossenen Bars anpassen

### 5.7 Management laufender Trend-Trades
- SL folgt dem mittleren Bollinger-Band des zuletzt abgeschlossenen Bars
- sobald Profit = initiales Risiko (1:1), wird der SL auf Break-even gesetzt
- Break-even hat Priorität gegenüber dem dynamischen SL
- TP bleibt das 2R-Ziel gemäss Orderlogik

---

## 6. Gegentrend-Signal

Der Gegentrend handelt gegen ein bestehendes Trendregime.

### 6.1 Voraussetzung
Ein Gegentrend-Signal kann nur entstehen, wenn ein Trendregime besteht.

### 6.2 Richtung
- bullishes Regime -> Gegentrend-Short
- bearishes Regime -> Gegentrend-Long

### 6.3 Neues Gegentrend-Signal
Ein neues Gegentrend-Signal kann nur am ersten abgeschlossenen Bar eines neuen Trendregimes entstehen.

Definition gemäss Spezifikation:
- der Signal-Bar schliesst deutlich ausserhalb des relevanten äusseren Bollinger-Bands
- Entry liegt auf dem Schlusskurs des Signal-Bars

### 6.4 Spätere Gegentrend-Konstellationen
Spätere Gegentrend-Konstellationen innerhalb desselben Trendregimes gelten nicht als neues Signal.

Sie sind nur relevant, wenn bereits ein Trend-Trade aktiv ist. In diesem Fall gehören sie zum Trade-Management.

### 6.5 Gegentrend als eigenständiger Trade
Ein Gegentrend ist immer ein echter, neuer Trade mit:
- eigenem Entry
- eigenem SL
- eigenem TP
- eigener Order-Logik

### 6.6 Gegentrend-Ordertyp
Der Ordertyp hängt von der Position des aktuellen Marktes relativ zum gewünschten Entry ab.

Regel:
- wenn der Markt über dem Ziel-Entry liegt und ein Short-Einstieg gewünscht ist -> Sell Limit
- wenn der Markt unter dem Ziel-Entry liegt und ein Short-Einstieg gewünscht ist -> Sell Stop
- wenn der Markt unter dem Ziel-Entry liegt und ein Long-Einstieg gewünscht ist -> Buy Stop
- wenn der Markt über dem Ziel-Entry liegt und ein Long-Einstieg gewünscht ist -> Buy Limit

### 6.7 Gegentrend-SL und Gegentrend-TP
- Fachregel: Gegentrend = 1R
- SL wird initial gemäss Gegentrend-Logik gesetzt und bleibt danach fix
- TP orientiert sich am mittleren Bollinger-Band
- TP wird bei laufendem Gegentrend-Trade auf das neue mittlere Bollinger-Band des zuletzt abgeschlossenen Bars angepasst

### 6.8 Management nicht gefillter Gegentrend-Orders
- Wird die Order bis zum nächsten Trading-Zeitpunkt nicht gefillt, wird sie gelöscht

---

## 7. Prioritäts- und Konfliktlogik

### 7.1 V1-Modus
V1 nutzt ausschliesslich den aggressiven Modus.

### 7.2 Gegentrend gegen laufenden Trendtrade
Wenn ein valides Gegentrend-Signal entsteht und ein Trend-Trade bereits aktiv ist, dann:
- der laufende Trend-Trade wird per Market Close beendet
- anschliessend wird der Gegentrend-Trade gemäss Orderlogik eröffnet

### 7.3 Kein vorheriger Trendtrade nötig
Ein Gegentrend-Signal braucht ein Trendregime, aber keinen bereits offenen Trend-Trade.

Das heisst:
- Trendregime aktiv -> Gegentrend-Signal kann entstehen
- Trendtrade aktiv -> optional

---

## 8. Order-Modul

Das Order-Modul darf ausschliesslich folgende Aktionen ausführen:
- Pending Orders setzen
- Pending Orders anpassen
- Pending Orders löschen
- offene Trades managen

Keine Market Orders, ausser:
- Market Close eines laufenden Trend-Trades beim aggressiven Reversal in einen Gegentrend

---

## 9. Zustandslogik (fachliche Sicht)

Der Agent kennt mindestens folgende Zustände:

### 9.1 Regime-Zustände
- neutral
- bullish
- bearish

### 9.2 Order-/Trade-Zustände
- keine aktive Order / keine Position
- pending Trend-Order
- aktiver Trend-Trade
- pending Gegentrend-Order
- aktiver Gegentrend-Trade

### 9.3 Verhaltenslogik
- neue Signale werden nur zu Trading-Zeit geprüft
- Trend-Signale und Gegentrend-Signale werden kontextabhängig bewertet
- bei Konflikten hat das aggressive Gegentrend-Reversal Vorrang gegenüber einem laufenden Trend-Trade

---

## 10. Parametrisierung für V1

Beispielhafte Konfigurationsparameter:

- inside_buffer_pct = 0.20
- outside_buffer_pct = 0.20
- min_bandwidth_avg_period = 30
- min_bandwidth_ratio = 0.70
- max_bars_since_regime_start_for_trend_signal = 6
- trading_times = konfigurierbare Prüfzeitpunkte
- break_even_rr = 1.0
- trend_tp_rr = 2.0

---

## 11. Nicht Teil von V1 / spätere Ausbaustufen

Folgende Themen sind bewusst nicht Teil von V1 oder nur angedeutet:
- konservativer Gegentrend-Modus (Break-even statt Reversal)
- zusätzliche Qualitäts- oder Scoring-Logik
- News-Filter
- Multi-Markt-spezifische Parameteroptimierung
- ML/KI-basierte Meta-Bewertung
- Broker- oder Prop-Firm-spezifische API-Integration

---

## 12. Technische Zielarchitektur (Vorstufe)

V1 soll in einer Python-basierten Struktur umgesetzt werden.

Empfohlene Module:
- regime detection
- indicator calculation
- signal detection
- decision engine
- order manager
- trade manager
- backtest / simulation runner
- logging / journal

Ziel ist zunächst ein deterministischer Strategy Core, bevor eine Broker- oder Prop-Firm-Anbindung erfolgt.
