# GitTool – Qt 6 (Windows und Linux)

Dieser Branch stellt eine moderne, plattformübergreifende **GUI mit PySide6/Qt 6**
für **Windows und Linux** bereit. Sie verwendet wie die Linux-GTK-Version die Python-Bibliothek
[gittyup](https://github.com/mikeckennedy/gittyup) von Michael Kennedy
(nicht die gleichnamige Gittyup-GUI).

**Branch-Übersicht:**
- [windows](https://github.com/Protarios/gittool/tree/windows): Qt6/PySide6 für Windows **und Linux**; ohne GTK, PyGObject oder MSYS2.
- [gpt](https://github.com/Protarios/gittool/tree/gpt): GTK4/libadwaita für Linux.

Die Git-Funktionen und das Konfigurationsformat sind identisch. Beim Wechsel
zwischen den Versionen auf demselben Rechner bleibt die Repository-Liste erhalten.

## Voraussetzungen

- **Windows 10/11 oder Linux** (64 Bit).
- **Python 3.13 oder 3.14**, mit pip und venv.
- Git for Windows; \`git.exe\` muss über \`PATH\` erreichbar sein.
- Netzwerkzugang und Git-Anmeldedaten/SSH-Schlüssel für Remote-Repositories.

GTK und \`python-gobject\` sind **nicht erforderlich**. PySide6 wird inklusive
Qt-Bibliotheken per pip installiert.

## Installation unter Windows (PowerShell)

~~~powershell
git clone --branch windows https://github.com/Protarios/gittool.git
cd gittool
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
gittool
~~~

Ist Python 3.13 installiert, ersetze \`py -3.14\` durch \`py -3.13\`.

**Bereits geklontes GitTool aktualisieren:**

~~~powershell
git fetch origin
git switch --track origin/windows
python -m pip install -e .
gittool
~~~

Wenn du einen lokalen Branch \`windows\` schon hast, verwende stattdessen:

~~~powershell
git switch windows
git pull --ff-only
python -m pip install -e .
gittool
~~~

Du kannst alternativ \`python -m gittool\` verwenden.
Ein erneuter pip-Aufruf ist nur nötig, wenn sich Python-Abhängigkeiten ändern.
Ein Paket, das mit \`pip install -e .\` installiert wurde, verwendet sonst
direkt die ausgecheckten Python-Quelldateien.

## Installation unter Linux

Für CachyOS, Arch Linux und andere Linux-Distributionen mit Python 3.13+:

~~~bash
git clone --branch windows https://github.com/Protarios/gittool.git
cd gittool
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
gittool
~~~

Ein zuvor vorhandenes GitTool-Repository auf `gpt` kannst du auf
`windows` umstellen:

~~~bash
git fetch origin
git switch --track origin/windows
python -m pip install -e .
gittool
~~~

Falls `windows` lokal bereits existiert, verwende
`git switch windows && git pull --ff-only`.
Es ist für die Qt-Version **nicht nötig**, `include-system-site-packages = true`
zu setzen oder `gi` zu installieren.

Die automatisierten GUI- und Backend-Tests laufen für **Linux und Windows**
mit **Python 3.13 und 3.14** (Qt unter Linux im Headless-Modus).

## Funktionalität

- Git-Repository über Dialog oder eingegebenen Pfad hinzufügen;
  übergeordneten Ordner rekursiv durchsuchen, inklusive Worktrees.
- Lokale Repository-Liste dauerhaft speichern.
- Ausgewählte oder alle Repositories auf Remote-Änderungen prüfen.
- Ausgewählte oder alle Repositories prüfen und sicher aktualisieren.
- Repository-Tabelle mit Branch, Upstream, geändert/sauber, Ahead, Behind,
  Status und Pfad; Spaltensortierung, Mehrfachauswahl und Suche.
- Farbcodierung (jeweils zusätzlich ein Klartext-Status):
  - **Grün:** aktuell
  - **Blau:** Pull möglich
  - **Orange:** lokale Änderungen/Commits, fehlendes Remote/Upstream
  - **Rot:** divergierter Branch, detached HEAD oder Fehler
  - **Grau:** noch nicht geprüft
- Protokoll und Fortschrittsanzeige; Git-Vorgänge laufen im Hintergrund,
  damit die Oberfläche bedienbar bleibt.

Die Statusprüfung nutzt \`git fetch\`, Gittyup und Git-Plumbing.
Der Pull wird durch
\`gittyup.git_operations.pull_repository_detailed()\` ausgeführt,
aber nur bei sauberem Arbeitsverzeichnis, eingerichtetem Upstream,
\`ahead=0\` und \`behind>0\`. Für den Kindprozess erzwingt GitTool
\`pull.ff=only\`. Lokale Änderungen, divergierte Branches oder
detached HEAD werden **nicht** automatisch gemergt, verworfen,
rebased oder gestasht. Git-LFS und Hooks laufen wie bei normalem Git.

Die Konfiguration enthält nur Pfade und wird unter
\`platformdirs.user_config_path("gittool", "Protarios")/repositories.json\`
gespeichert.

## Tests

~~~powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
Remove-Item Env:\QT_QPA_PLATFORM
~~~

Der Windows-GUI-Test erzeugt ein Qt-Fenster ohne angeschlossenen Bildschirm,
prüft Suche, Auswahl, die Statusfarben und deren Zuordnung. Dazu kommen
die Offline-Git-Tests mit echten lokalen Test-Repositories.

## Projektstruktur

- \`gittool/app.py\`: PySide6/Qt6-Fenster, farbige Tabelle und Worker-Events.
- \`gittool/status_style.py\`: Status-Kategorien, gemeinsam mit GTK-Version.
- \`gittool/backend.py\`: Gittyup-Backend und Fast-Forward-Sicherheitsprüfungen.
- \`gittool/config.py\`: persistente Repository-Liste.
- \`tests/\`: Backend- und GUI-Tests.
