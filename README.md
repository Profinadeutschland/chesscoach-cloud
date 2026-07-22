# ErtuCoach Cloud

Live-Dashboard + nächtliche Stockfish-Analyse für AirT007 (Chess.com), komplett auf GitHub:
GitHub **Pages** hostet die Seite, GitHub **Actions** analysiert jede Nacht neue Partien mit Stockfish
und schreibt das Ergebnis nach `data/engine.json` – die Seite lädt beides automatisch.

```
index.html                       Live-Dashboard (aktualisiert sich selbst von der Chess.com-API)
data/engine.json                 Engine-Ergebnisse (füllt der Nacht-Job)
scripts/engine_analyze.py        Stockfish-Analyse, inkrementell
.github/workflows/nightly.yml    Zeitplan: jede Nacht 04:23 deutscher Zeit
```

## Einmaliges Setup (~10 Minuten)

1. **Repo anlegen:** Auf github.com → *New repository* → Name z. B. `ertucoach-cloud`.
   *Private* funktioniert (Actions-Freiminuten reichen locker), *Public* hat unbegrenzte Minuten –
   die Schachdaten sind ohnehin öffentlich.

2. **Hochladen** (Terminal, in diesem Ordner):
   ```bash
   cd ~/Projects/chesscoach/ertucoach-cloud
   git init && git add -A && git commit -m "ErtuCoach Cloud"
   git branch -M main
   git remote add origin git@github.com:DEIN-NAME/ertucoach-cloud.git
   git push -u origin main
   ```

3. **Pages aktivieren:** Repo → *Settings → Pages* → Source: *Deploy from a branch* →
   Branch `main`, Ordner `/ (root)` → Save.
   Nach ~1 Minute läuft die Seite unter `https://DEIN-NAME.github.io/ertucoach-cloud/`.
   (Bei privatem Repo ist die Pages-URL trotzdem öffentlich erreichbar, nur nicht verlinkt –
   wie bei Netlify. Echter Zugriffsschutz ginge später über Cloudflare Access.)

4. **Backfill starten** (einmalig alle 800+ Partien mit Engine durchrechnen):
   Repo → *Actions* → *Nightly Engine Analysis* → *Run workflow* → `max_games` auf `400` setzen → Run.
   Zwei Läufe à ~60–90 Min., dann ist alles aufgeholt. Danach läuft es von allein:
   jede Nacht 04:23 Uhr, ~10–20 neue Partien, ~5 Minuten.

## Was die Seite dann kann

Alles aus der bisherigen Live-Seite (Level-System, Gates, Skills, Uhrzeit-Heatmap, Session-Analyse,
Fehler-Kino, letzte Partien) **plus** das Engine-Panel: ACPL-Trend (durchschnittlicher
Zentibauern-Verlust), echte Engine-Blunder (≥ 200 cp), verpasste Matts, Phasen-ACPL und die
gröbsten Blunder mit Direktlink. Browser-Heuristik = sofort & live, Engine = präzise & nächtlich.

## Wendepunkt-Analyse (v2)

Der Nacht-Job findet pro Partie zusätzlich die 1–2 **Wendepunkte** (größte Eval-Umschwünge:
verpasster Gewinnzug oder Kollaps), analysiert genau diese Stellungen extra tief
(`DEEP_DEPTH`, Default 20, mit MultiPV) und klassifiziert das Motiv menschlich:
Springergabel, hängende Figur, Fesselung, Abzug, Grundreihenmatt, Mattkombination,
Umwandlung, Zwischenschach … Die Seite zeigt dazu animierte Bretter mit der Gewinnfolge,
eine persönliche Muster-Statistik („worauf falle ich am häufigsten rein") und den
kuratierten Fallen-Guide für den Bereich 600–1000 Elo.

**Wichtig:** Partien, die schon in `data/engine.json` stehen, werden nicht neu angefasst.
Wenn du die Wendepunkte rückwirkend für ALLE Partien willst: `data/engine.json` wieder auf
`{"updated":null,"games":{}}` zurücksetzen, committen und den Backfill erneut laufen lassen
(Actions → Run workflow → `max_games: 400`, zwei Läufe).

## Anpassen

- Suchtiefe Eval-Kurve: `DEPTH` in `nightly.yml` (12 = guter Kompromiss; 14 ≈ 3× langsamer).
- Suchtiefe Wendepunkte: `DEEP_DEPTH` (Default 20 – hier lohnt Tiefe, es sind nur 1–2 Stellungen pro Partie).
- Partien pro Nachtlauf: `MAX_GAMES` (Default 150).
- Zeitplan: `cron` in `nightly.yml` (UTC!).
