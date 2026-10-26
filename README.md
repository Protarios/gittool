# GitTool

Eine plattformübergreifende Python-GUI (Tkinter) zum Prüfen und Aktualisieren
mehrerer **lokaler Git-Repositories** mit dem Python-Paket
[gittyup von Michael Kennedy](https://github.com/mikeckennedy/gittyup).
Es handelt sich **nicht** um den gleichnamigen GUI-Git-Client.

## Funktionen

- Repository-Stammordner per Pfad oder Dateiauswahl hinzufügen.
- Ganze Verzeichnisbäume nach Repositories durchsuchen, einschließlich
  Git-Worktrees mit einer .git-Datei.
- Repository-Liste dauerhaft im Benutzerkonfigurationsverzeichnis speichern.
- Status der Auswahl oder aller Repositories auf Knopfdruck prüfen:
  Remote-Fetch, Branch, Upstream, uncommittete Dateien und Ahead/Behind-Zähler.
- **Auswahl oder alle Repositories mit einem Klick prüfen und pullen**.
- Pull ausschließlich bei sauberem Arbeitsverzeichnis, eingerichtetem Upstream
  und reinem Fast-Forward. Lokale Commits, divergierte Branches, detached HEAD
  und uncommittete Dateien bleiben unberührt.
- Hintergrundverarbeitung, Fortschrittsanzeige und detailliertes Protokoll.

## Voraussetzungen

- Python **3.13 oder neuer** (Voraussetzung von gittyup 1.2).
- Git muss installiert und im PATH sein.
- Tkinter muss verfügbar sein. Unter Linux ist dafür ggf. das Paket
  python3-tk bzw. die passende Tk-Bindung erforderlich.
- Zugriff auf die Remotes per SSH oder eingerichtetem Git-Credential-Manager.
  Terminal-Passwortabfragen sind ausgeschaltet, damit die GUI nicht hängt.

## Installation und Start

Linux/macOS:

~~~bash
git clone -b gpt https://github.com/Protarios/gittool.git
cd gittool
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m gittool
~~~

Windows (PowerShell):

~~~powershell
git clone -b gpt https://github.com/Protarios/gittool.git
cd gittool
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m gittool
~~~

Alternativ nach der Installation den GUI-Startbefehl **gittool** verwenden.

## Bedienung

1. **Ordner wählen …** für einzelne Repositories oder **Ordner durchsuchen …**
   für einen ganzen übergeordneten Verzeichnisbaum.
2. **Alle prüfen** aktualisiert die Remote-Tracking-Informationen per git fetch
   und zeigt den aktuellen Stand, ohne lokale Branches zu verändern.
3. **Alle: prüfen + Pull** prüft jedes Repository vor dem Pull und aktualisiert
   ausschließlich Repositories, die als Fast-Forward aktualisiert werden können.
4. Mit Strg oder Umschalt lassen sich einzelne Zeilen markieren und Aktionen
   auf diese Auswahl beschränken.

**Sicherheitsregeln:** GitTool wirkt immer auf den aktuell ausgecheckten Branch.
Es wechselt keine Branches, macht keinen Push, Reset, Stash, Merge oder Rebase
als eigenen Arbeitsschritt. Der eigentliche Pull wird über die Python-API
gittyup.git_operations.pull_repository_detailed() ausgeführt. Weil diese
einen normalen git pull aufruft, erzwingt GitTool die Git-Einstellungen
pull.ff=only und pull.rebase=false *nur für diesen Kindprozess*.
Keine dauerhaften Git-Konfigurationsänderungen.

Git-LFS-Filter, Git-Hooks und andere Git-Mechanismen können beim regulären
git pull weitere Aktionen ausführen; GitTool deaktiviert sie nicht.
Ein Fehler bei einem Repository wird protokolliert und die weiteren werden
trotzdem verarbeitet.

Die gespeicherte Liste enthält nur **lokale Pfade**, keine Zugangsdaten.
Sie liegt unter dem von platformdirs bestimmten Pfad
gittool/repositories.json im Benutzerkonfigurationsverzeichnis.

## Entwickeln und testen

~~~bash
python -m unittest discover -s tests -v
~~~

Die Kerntests verwenden lokale Test-Repositories und kein externes Netzwerk.

## Technischer Aufbau

- gittool/app.py – Desktop-GUI und sequenzieller Hintergrund-Worker.
- gittool/backend.py – Gittyup-API, Fetch, Ahead/Behind, Sicherheitschecks.
- gittool/config.py – atomare persistente Ablage der Repository-Liste.
- tests/ – Offline-Tests für Konfiguration und Git-Verhalten.

Entwicklungsbranch: [gpt](https://github.com/Protarios/gittool/tree/gpt).
