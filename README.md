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
- **Auswahl prüfen**, **Alle prüfen**, **Auswahl prüfen + Pull** und
  **Alle prüfen + Pull**, mit Fortschrittsanzeige und Protokoll.
- **Farbcodierung über libadwaita-Themenfarben:** Grün = aktuell,
  Blau = Pull möglich, Orange = lokale Änderungen / lokale Commits /
  fehlender Upstream, Rot = divergiert, detached HEAD oder Git-Fehler,
  Grau = ungeprüft. Die Zustände stehen zusätzlich als Klartext da
  (auch ohne Farbwahrnehmung unterscheidbar).
- Sichere Aktualisierung: Gittyup zieht nur über ein sauberes Arbeitsverzeichnis
  mit Upstream und Fast-Forward. Divergenzen und uncommittete Änderungen
  werden nicht automatisch gemergt oder verworfen.
- Gespeicherte Repository-Pfade werden aus der vorherigen Tkinter-Version
  unverändert übernommen.

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
4. Die Auswahlkästchen erlauben Aktionen auf einzelne Repositories.
   Die Suchzeile filtert die Ansicht, nicht die gespeicherte Repository-Liste.
5. Das Protokoll zeigt Erfolge, übersprungene Repositories und Fehler.

Die automatische Aktualisierung führt **kein** `reset`, `stash`,
`push` und keinen selbstständigen Branch-Wechsel aus. Der eigentliche
Pull erfolgt mit
`gittyup.git_operations.pull_repository_detailed()`. GitTool erzwingt
`pull.ff=only` temporär für diesen Git-Prozess, nicht in der
Git-Konfiguration des Repositories. Git-Hooks und Git-LFS-Filter können
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
