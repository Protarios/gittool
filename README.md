# GitTool

Moderne **GTK 4 + libadwaita**-Anwendung zur Statusprüfung und zum sicheren Aktualisieren
mehrerer lokaler Git-Repositories unter Linux. Der Git-Backend verwendet die
**Python-Bibliothek [gittyup](https://github.com/mikeckennedy/gittyup)**,
nicht den gleichnamigen grafischen Git-Client.

GTK 5 ist derzeit nicht als stabile API verfügbar; das Projekt setzt
wie der DAR Explorer auf PyGObject / GTK 4.

## Funktionen

- Repository-Pfade eingeben, Ordner über den Dateidialog hinzufügen oder
  ganze Verzeichnisbäume einschließlich Git-Worktrees durchsuchen.
- Auswahl per Kontrollkästchen und Volltextsuche nach Repository, Pfad,
  Branch, Upstream oder Status.
- Statusprüfung per Fetch sowie Anzeige von Branch, Upstream, Ahead/Behind und
  lokalen Änderungen.
- **Auswahl prüfen**, **Alle prüfen**, **Lokal prüfen** (ohne Netzwerk),
  **Auswahl prüfen + Pull** und **Alle prüfen + Pull**, mit Fortschrittsanzeige
  und Protokoll. Statusprüfungen laufen mit bis zu vier parallelen Workern.
  Der eigentliche Pull bleibt aus Sicherheitsgründen sequenziell.
- **Farbcodierung über libadwaita-Themenfarben:** Grün = aktuell,
  Blau = Pull möglich, Orange = lokale Änderungen / lokale Commits /
  fehlender Upstream, Rot = divergiert, detached HEAD oder Git-Fehler,
  Grau = ungeprüft. Die Zustände stehen zusätzlich als Klartext da
  (auch ohne Farbwahrnehmung unterscheidbar).
- **Sichere Aktualisierung auch bei lokalen Änderungen:** Generierte,
  unversionierte PDF-Dateien müssen weder committet noch ignoriert werden.
  Vor einem möglichen Fast-Forward-Pull vergleicht GitTool die lokalen Dateien
  mit den eingehenden Dateipfaden, zeigt die vollständige Änderungsliste und
  fragt ausdrücklich nach einer Freigabe. Überschneidungen sperren den Pull;
  ohne Freigabe geschieht nichts. Git prüft zusätzlich auf Überschreibungen.
  Kein implizites Stash, Reset, Rebase oder erzwungener Merge.
- Getrennte Statusmeldungen **„Lokal geändert · Aktuell“**,
  **„Lokal geändert · Pull möglich“** und **„Lokal geändert · Lokal voraus“**;
  korrektes Diagnoseergebnis **„Tracking-Ref fehlt“** bei konfiguriertem,
  aber nicht auflösbarem Upstream.
- **Schneller Start:** gespeicherte Repositories werden in einem Durchgang
  geladen, initialisierte Submodule erst danach im Hintergrund zugeordnet.
  Ordnerscans fügen gefundene Repositories gesammelt hinzu.
- Gespeicherte Repository-Pfade werden aus der vorherigen Tkinter-Version
  unverändert übernommen.

## Programmsymbol

Die Linux-GTK-Version verwendet dasselbe transparente GitTool-Icon wie die
Qt-Version: `gittool/assets/gittool.png`. Es ist als Python-Paketressource
enthalten und wird beim Start in den GTK-Icon-Suchpfad aufgenommen sowie als
Fenster-Icon (`gittool`) gesetzt, unabhängig vom Arbeitsverzeichnis.

Für das Linux-Anwendungsmenü kann der mitgelieferte Desktopstarter
inklusive des **neuen** Icons benutzerspezifisch installiert werden
(kein Root erforderlich):

~~~bash
python scripts/install_linux_desktop.py
~~~

Das Skript verwendet den aktuell aktiven Python-Interpreter (auch aus einer
virtuellen Umgebung) und legt den Starter in
`~/.local/share/applications/io.github.protarios.gittool.desktop`
sowie das Icon im XDG-Hicolor-Verzeichnis ab. Entfernen:

~~~bash
python scripts/install_linux_desktop.py --uninstall
~~~

Die Qt-Version im Branch `windows` verwendet dasselbe neue Motiv für die
Windows-EXE, das Qt-Fenster und die Taskleiste.

## Reihenfolge und Submodule

Die Repository-Liste speichert jetzt eine **manuell festgelegte Reihenfolge**.
Mit **↑ Nach oben** und **↓ Nach unten** verschiebst du das ausgewählte
Repository um eine Position zwischen seinen Geschwistern. Ein Hauptrepository
nimmt dabei alle untergeordneten Submodule mit. Das Verschieben erfolgt
auch bei einem Neustart in derselben Reihenfolge.

Beim **Hinzufügen** eines Repositories (auch über die Ordnersuche) und
beim **Laden der gespeicherten Liste** erkennt GitTool *im Hintergrund* die
initialisierten Git-Submodule über die Gitlinks des Git-Index, rekursiv
einschließlich verschachtelter Submodule. Die Oberfläche wartet nicht auf
diese Git-Prozesse. Diese erhalten einen expliziten Parent und
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

## Installation unter Linux

Voraussetzungen: **Python 3.13+**, Git, GTK **4.10+**, libadwaita und
PyGObject (Python-Modul `gi`).

**Arch Linux / CachyOS / EndeavourOS / Manjaro:**

~~~bash
sudo pacman -S --needed git python python-gobject gtk4 libadwaita
~~~

**Debian / Ubuntu (mit passender Python-Version):**

~~~bash
sudo apt install git python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
~~~

Das Python-Paket `gittyup` benötigt **Python >= 3.13**. Falls die
Distribution eine ältere System-Python-Version verwendet, muss eine
separate Python-3.13+-Umgebung samt kompatiblen PyGObject-Bindings
eingerichtet werden. Die Systempakete alleine reichen dann nicht
immer für ein zusätzlich installiertes Python.

**Wichtig bei `.venv`:** Die üblichen Python-Virtualenvs blenden
System-Pakete aus. Damit das systemweit installierte PyGObject in
der virtuellen Umgebung sichtbar wird, erstelle diese mit
`--system-site-packages` (Python-Version muss zur Systembindung passen):

~~~bash
git clone -b gpt https://github.com/Protarios/gittool.git
cd gittool
python -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e .
gittool
~~~

Wenn du wie bisher bereits eine funktionierende `.venv` angelegt hast,
kannst du die vorhandene Umgebung beibehalten und in
`.venv/pyvenv.cfg` die Zeile

~~~ini
include-system-site-packages = true
~~~

setzen. **Nur wenn** das System-`python-gobject` zur exakt
gleichen Python-Version passt, ist `import gi` damit verfügbar.
Prüfe mit:

~~~bash
python -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw; print('GTK verfügbar')"
~~~

Wenn die Systembindung nicht zur Python-Version passt, müssen
PyGObject und Pycairo in der virtuellen Umgebung mit den passenden
System-Entwicklungspaketen installiert werden; siehe
[offizielle PyGObject-Anleitung](https://pygobject.gnome.org/getting_started.html).

**Projekt bereits vorhanden?** Im Branch `gpt` wechseln und aktualisieren:

~~~bash
git fetch origin
git switch gpt                 # Falls der lokale Branch bereits existiert
git pull --ff-only
python -m pip install -e .
gittool
~~~

Wenn es noch keinen lokalen `gpt`-Branch gibt,
anstelle von `git switch gpt` einmal
`git switch --track origin/gpt` ausführen.

Die direkte Startform `python -m gittool` funktioniert ebenfalls.

## Bedienung

1. Links oben mit **+** einen Repository-Stammordner hinzufügen, mit dem
   Suchordnersymbol mehrere Repositories unterhalb eines Verzeichnisses
   finden oder den Pfad direkt eingeben.
2. **Alle prüfen** ruft bei jedem Repository `git fetch` auf und zeigt
   an, ob Remote-Commits vorliegen (↑ Ahead / ↓ Behind).
3. **Alle prüfen + Pull** versucht ausschließlich sichere Fast-Forwards.
   Bei lokalen Änderungen erscheint eine Liste mit allen geänderten und
   unversionierten Dateien. Wenn keine dieser Dateien durch den Pull berührt
   würde, kann der Pull bestätigt oder übersprungen werden.
4. Die Auswahlkästchen erlauben Aktionen auf einzelne Repositories.
   Die Suchzeile filtert die Ansicht, nicht die gespeicherte Repository-Liste.
5. Das Protokoll zeigt Erfolge, übersprungene Repositories und Fehler.

Die automatische Aktualisierung führt **kein** `reset`, `stash`,
`push` und keinen selbstständigen Branch-Wechsel aus. Für unveränderte Arbeitsverzeichnisse läuft der eigentliche Pull über
`gittyup.git_operations.pull_repository_detailed()` und GitTool erzwingt
`pull.ff=only` temporär im Git-Prozess. Bei ausdrücklich freigegebenen
lokalen Änderungen verwendet GitTool nach erneuter Prüfung
`git merge --ff-only <geprüfter Commit>` ohne einen weiteren Netzwerk-Fetch.
Damit bleibt der bestätigte Ziel-Commit festgelegt; die Git-Konfiguration
des Repositories wird nicht dauerhaft verändert. Git-Hooks und Git-LFS-Filter können
wie bei einem normalen `git pull` trotzdem ausgeführt werden.

Die Repository-Liste enthält **keine Zugangsdaten**, sondern nur Pfade.
Sie liegt im von `platformdirs` ermittelten Benutzer-Konfigurationsverzeichnis
unter `gittool/repositories.json`.

## Tests

~~~bash
python -m unittest discover -s tests -v
~~~

Die Backend-Tests verwenden lokale Git-Repositories. Der Linux-CI-Lauf
testet zusätzlich den Start des GTK-Fensters in Xvfb.

## Aufbau

- `gittool/app.py`: GTK4/libadwaita GUI, Farbanzeige, Hintergrund-Worker.
- `gittool/status_style.py`: Zustands- und Farbcodes unabhängig vom GUI.
- `gittool/backend.py`: Gittyup-Anbindung, Fetch, Ahead/Behind und Pull-Schutz.
- `gittool/config.py`: atomare Speicherung der bisherigen Pfadliste.
- `tests/`: Git-Backend- und GUI-Regressionsprüfungen.

Entwicklung: [Branch gpt](https://github.com/Protarios/gittool/tree/gpt).
