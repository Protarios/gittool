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
- Git for Windows; `git.exe` muss über `PATH` erreichbar sein.
- Netzwerkzugang und Git-Anmeldedaten/SSH-Schlüssel für Remote-Repositories.

GTK und `python-gobject` sind **nicht erforderlich**. PySide6 wird inklusive
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

Ist Python 3.13 installiert, ersetze `py -3.14` durch `py -3.13`.

**Bereits geklontes GitTool aktualisieren:**

~~~powershell
git fetch origin
git switch --track origin/windows
python -m pip install -e .
gittool
~~~

Wenn du einen lokalen Branch `windows` schon hast, verwende stattdessen:

~~~powershell
git switch windows
git pull --ff-only
python -m pip install -e .
gittool
~~~

Du kannst alternativ `python -m gittool` verwenden.
Ein erneuter pip-Aufruf ist nur nötig, wenn sich Python-Abhängigkeiten ändern.
Ein Paket, das mit `pip install -e .` installiert wurde, verwendet sonst
direkt die ausgecheckten Python-Quelldateien.

## Linux-AppImage (x86_64)

Aus dem jeweiligen Branch erzeugt GitHub Actions eine eigene Linux-AppImage
mit dem neuen GitTool-Icon:

- `windows`: Qt6/PySide6, Ausgabe `GitTool-Qt-x86_64.AppImage`.
- `gpt`: GTK4/libadwaita, Ausgabe `GitTool-GTK-x86_64.AppImage`.

Den Build findest du unter
[GitHub Actions · Linux AppImage](https://github.com/Protarios/gittool/actions/workflows/build-appimage.yml).
Auf den gewünschten Branch achten und unter **Artifacts** das zugehörige
`GitTool-Linux-AppImage-windows` bzw. `GitTool-Linux-AppImage-gpt` laden.

Nach dem Entpacken des Actions-Artifacts:

~~~bash
chmod +x GitTool-*-x86_64.AppImage
./GitTool-*-x86_64.AppImage
~~~

Die AppImage benötigt keine separate Python-Umgebung, aber **Git** muss auf
dem Zielrechner installiert und über `PATH` verfügbar sein. Beide Varianten
werden auf Ubuntu 24.04 gebaut, weshalb der Einsatz auf deutlich älteren
Linux-Distributionen nicht garantiert ist. Der Workflow führt nach jedem
Build einen echten Starttest über einen virtuellen X11-Bildschirm aus.

Wenn das System keine FUSE-Unterstützung für AppImage bereitstellt, kann
`APPIMAGE_EXTRACT_AND_RUN=1 ./GitTool-*-x86_64.AppImage` verwendet werden.
Der eigene lokale Entwicklungsstart über `python -m gittool` bleibt unverändert.

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

## Geschwindigkeit und Statusprüfung

- **Schneller Programmstart:** Die gespeicherten Repositories werden in einem
  Durchgang angezeigt. Die initialisierten Submodule werden im Hintergrund
  geprüft und bei Bedarf anschließend ergänzt. Die Oberfläche wartet dabei
  nicht auf Git-Prozesse.
- **Lokal prüfen:** Schneller Statuscheck ohne `git fetch`. Zeigt den Stand der
  *zuletzt lokal bekannten Remote-Tracking-Refs* an; neue Commits auf dem
  Server erscheinen erst nach einem Fetch.
- **Alle prüfen:** Führt weiterhin `git fetch` aus, prüft jedoch bis zu vier
  voneinander unabhängige Repositories parallel. Laufzeit hängt von Netzwerk,
  Repository-Größe und Anmeldedaten ab.
- **Prüfen + Pull:** Bleibt absichtlich sequenziell und erzwingt
  Fast-Forward-only. Bei lokalen Änderungen prüft GitTool sämtliche
  unversionierten, gestagten und geänderten Dateien gegen die Pfade der
  eingehenden Commits und zeigt einen Bestätigungsdialog an. Gibt es
  Überschneidungen, ist der Pull gesperrt. GitTool führt keine parallelen
  Pulls in zusammenhängenden Worktrees aus.
- **Schnellerer lokaler Git-Status:** Die Angaben für Branch, Upstream,
  Ahead/Behind und lokale Änderungen kommen aus `git status --porcelain=v2`
  statt aus mehreren separaten Git-Aufrufen.

Der schnelle Lokalmodus kann ohne Netzwerkverbindung benutzt werden;
er ersetzt keine Aktualisierung der Remote-Tracking-Refs.

## Reihenfolge und Submodule

Die Repository-Liste speichert jetzt eine **manuell festgelegte Reihenfolge**.
Mit **↑ Nach oben** und **↓ Nach unten** verschiebst du das ausgewählte
Repository um eine Position zwischen seinen Geschwistern. Ein Hauptrepository
nimmt dabei alle untergeordneten Submodule mit. Das Verschieben erfolgt
auch bei einem Neustart in derselben Reihenfolge.

Beim **Hinzufügen** eines Repositories (auch über die Ordnersuche) und
beim **Laden der gespeicherten Liste** erkennt GitTool die *initialisierten*
Git-Submodule über die Gitlinks des Git-Index, rekursiv einschließlich
verschachtelter Submodule. Diese erhalten einen expliziten Parent und
werden unter dem jeweiligen Hauptrepository angezeigt.
Submodule mit noch nicht ausgechecktem Worktree werden **nicht** automatisch
geklont oder initialisiert; dazu muss zunächst manuell
`git submodule update --init --recursive` ausgeführt werden.
Ein Submodul in **detached HEAD** wird zwar angezeigt und geprüft,
aber nicht automatisch gepullt.

Die Repository-Liste wird im rückwärtskompatiblen JSON-Format Version 2
gespeichert: `repositories` enthält Pfad- und Parent-Einträge in Reihenfolge.
Dateien älterer Version 1 werden ohne Verlust der Reihenfolge übernommen.
**Entfernen** eines Hauptrepositories löscht auch die zugehörigen Submodule
aus der *Liste*, niemals von der Festplatte.

## Windows-EXE ohne Terminal mit PyInstaller

Der Branch enthält den **absolut importierenden Einstiegspunkt**
`gittool_launcher.py` und ein PowerShell-Buildskript. Der GUI-Modus von
PyInstaller (`--windowed`) startet **ohne Konsolenfenster**. Anders als
`gittool/__main__.py` ist der Launcher für PyInstaller ein reguläres Skript.

Im Windows-PowerShell-Terminal aus dem Projektverzeichnis und mit Python
3.13/3.14:

~~~powershell
.\scripts\build_windows.ps1
~~~

Ergebnis: `dist\GitTool\GitTool.exe`. Der **gesamte Ordner**
`dist\GitTool` wird zur Weitergabe benötigt. Wer stattdessen eine
einzelne EXE möchte:

~~~powershell
.\scripts\build_windows.ps1 -Layout onefile
~~~

Ergebnis: `dist\GitTool.exe`. Bei `--onefile` entpackt die EXE beim
Start die Python- und Qt-Bibliotheken in ein temporäres Verzeichnis.

Alternativer manueller Build:

~~~powershell
python -m pip install pyinstaller pillow
python scripts/create_icons.py
python -m PyInstaller --noconfirm --clean --windowed --onedir --name GitTool --icon build/icons/GitTool.ico --paths . --collect-submodules gittyup --collect-data gittool gittool_launcher.py
~~~

### Plattformübergreifendes Programmsymbol

Das ausgewählte GitTool-Icon liegt als transparentes Paket-Asset unter
`gittool/assets/gittool.png` und ist als Paketdaten in `pyproject.toml`
eingetragen. Die Qt-Anwendung setzt dieses Symbol sowohl für das
Programmfenster als auch als Standard-Anwendungssymbol, unabhängig vom
aktuellen Arbeitsverzeichnis.

- **Windows:** Das Buildskript erstellt mit Pillow automatisch eine ICO-Datei
  mit 16, 24, 32, 48, 64, 128 und 256 Pixeln und übergibt sie an PyInstaller.
  Somit besitzt die erzeugte `GitTool.exe` auch im Explorer ihr eigenes Icon.
- **Linux (Qt):** Beim Start über `gittool` oder `python -m gittool`
  verwendet das Qt-Fenster dasselbe Symbol. Für Desktop-Menüeinträge muss
  das PNG gegebenenfalls zusätzlich als System-Icon installiert werden.
- **macOS (Qt):** Die Laufzeit lädt dasselbe PNG. Bei einem Build auf macOS
  kann `python scripts/create_icons.py` zusätzlich ein ICNS erzeugen;
  ein vollständiger macOS-Anwendungsbuild wird noch nicht durch CI geprüft.

Pillow ist nur für die Icon-Erzeugung beim Paketbau nötig, nicht als
Laufzeitabhängigkeit von GitTool.

GitTool enthält Qt/Python, **nicht Git für Windows**. Auf Zielrechnern
muss `git.exe` weiterhin über den `PATH` erreichbar sein.

**Keine aufblinkenden Terminalfenster:** Zusätzlich zum PyInstaller-Schalter
`--windowed` startet GitTool alle eigenen synchronen Git-Unterprozesse
unter Windows mit `subprocess.CREATE_NO_WINDOW`. Das gilt auch für
Gittyups synchronen Git-Prozessstarter, der für die Statusprüfung und
das Pull verwendet wird. Dadurch sind beim Start (automatische
Submodule-Erkennung) und bei regulären Git-Aktionen keine zusätzlichen
Konsolenfenster der Git-Prozesse sichtbar; die Protokollausgaben und
Fehlertexte bleiben erhalten.

Hinweis: Extern gestartete Credential-Manager oder Git-Hooks können
eigenständige Benutzeroberflächen besitzen; diese werden nicht
pauschal unterdrückt.

Der GitHub-Actions-Workflow
[Windows EXE (PyInstaller)](https://github.com/Protarios/gittool/actions/workflows/build-windows-exe.yml)
erstellt und prüft bei Push in den Branch `windows` automatisch einen
portablen Build. Die ZIP-Datei steht als Workflow-Artefakt bereit und
kann aus GitHub Actions heruntergeladen werden.

## Funktionalität

- Git-Repository über Dialog oder eingegebenen Pfad hinzufügen;
  übergeordneten Ordner rekursiv durchsuchen, inklusive Worktrees.
- Repository-Hierarchie und manuelle Reihenfolge dauerhaft speichern.
- Ausgewählte oder alle Repositories auf Remote-Änderungen prüfen.
- Ausgewählte oder alle Repositories prüfen und sicher aktualisieren.
- Repository-Tabelle mit Branch, Upstream, geändert/sauber, Ahead, Behind,
  Status und Pfad; hierarchische Darstellung, Mehrfachauswahl und Suche.
- Farbcodierung (jeweils zusätzlich ein Klartext-Status):
  - **Grün:** aktuell
  - **Blau:** Pull möglich
  - **Orange:** lokale Änderungen/Commits, fehlendes Remote/Upstream
  - **Rot:** divergierter Branch, detached HEAD oder Fehler
  - **Grau:** noch nicht geprüft
- Protokoll und Fortschrittsanzeige; Git-Vorgänge laufen im Hintergrund,
  damit die Oberfläche bedienbar bleibt.

Die Statusprüfung nutzt `git fetch`, Gittyup und Git-Plumbing.
Bei **sauberem Arbeitsverzeichnis** und `ahead=0`, `behind>0` verwendet
GitTool weiterhin `gittyup.git_operations.pull_repository_detailed()`
mit erzwungenem `pull.ff=only`.

### Getrennte Statusanzeigen bei lokalen Änderungen

Die Statusspalte unterscheidet ausdrücklich:

- **Lokal geändert · Aktuell:** Dateien sind lokal geändert oder unversioniert,
  aber es sind keine Remote-Commits ausstehend.
- **Lokal geändert · Pull möglich:** Remote-Commits sind vorhanden und lokale
  Dateien sind geändert/unversioniert. Der Pull kann nach der Dateiprüfung
  und ausdrücklicher Bestätigung erfolgen, wenn keine Pfade kollidieren.
- **Lokal geändert · Lokal voraus:** Lokal geänderte Dateien und eigene
  Commits, aber kein sicherer automatischer Fast-Forward.

Die blaue Kennzeichnung für einen anstehenden Pull hebt die
Bestätigungspflicht nicht auf.

### Pull trotz lokaler Dateien (z. B. generierte LaTeX-PDFs)

Wenn eingehende Commits vorhanden sind und GitTool **lokale Änderungen**
findet, erscheint vor einem Pull ein modaler Dialog:

1. Er listet alle nicht ignorierten **unversionierten**, **modifizierten**
   sowie **gestagten** Dateipfade mit Git-Statuscode auf.
2. GitTool vergleicht sie mit den Pfaden, die zwischen `HEAD` und dem
   zuvor gefetchten `@{upstream}` geändert werden; auch mögliche
   Datei-/Verzeichnisüberschneidungen zählen.
3. **Ohne Überschneidung:** Wahl zwischen **Pull durchführen** und
   **Überspringen**. Die Zustimmung gilt nur für diesen Pull und wird
   nicht gespeichert. Vor dem Update überprüft GitTool Branch, Refs und
   die Liste lokaler Änderungen erneut und führt ein `git merge --ff-only`
   auf den zuvor geprüften Commit aus. Das ist hier die lokale,
   netzwerkfreie Fast-Forward-Phase des Pulls.
4. **Mit Überschneidung:** GitTool zeigt die betroffenen Dateien und
   bietet ausschließlich **Überspringen** an. Kein Überschreiben und
   kein automatisches Stash/Commit.

**Wichtig:** Ein Fast-Forward-Pull erzeugt keinen Merge-Commit.
Git schützt zusätzlich vor dem Überschreiben lokaler Änderungen.
Bei unerwarteten Änderungen oder einem Git-Fehler wird abgebrochen.
Nicht versionierte, **ignorierte** Dateien erscheinen nicht in der
Dateiliste; GitTool behandelt sie wie Git im Standardzustand.

Divergierte Branches, fehlende Upstreams und detached HEAD bleiben
weiterhin gesperrt. Git-LFS und Hooks laufen wie bei normalem Git.

Die Konfiguration enthält nur Pfade und wird unter
`platformdirs.user_config_path("gittool", "Protarios")/repositories.json`
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

- `gittool/app.py`: PySide6/Qt6-Fenster, farbige Tabelle und Worker-Events.
- `gittool/status_style.py`: Status-Kategorien, gemeinsam mit GTK-Version.
- `gittool/backend.py`: Gittyup-Backend und Fast-Forward-Sicherheitsprüfungen.
- `gittool/config.py`: persistente Repository-Liste.
- `tests/`: Backend- und GUI-Tests.
