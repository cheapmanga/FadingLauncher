"""Point d'entrée pour le lancement direct et la compilation en .exe.

`fe_launcher/app.py` utilise des imports relatifs (`from .ui...`), qui n'existent que
si le paquet est importé, pas exécuté comme script. PyInstaller, lui, part d'un fichier :
ce module sert de pont. On peut aussi lancer l'app avec `python run.py`.
"""

from fe_launcher.app import main

if __name__ == "__main__":
    raise SystemExit(main())
