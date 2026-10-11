# apkg2forms

Convierte un mazo de Anki (`.apkg`) en un script de Google Apps Script que crea **Formularios de Google en modo test** (con respuestas correctas y 1 punto por pregunta). Sin IA, sin APIs, solo Python estándar.

## Uso
```
python apkg2forms.py            # interfaz gráfica (macOS, Windows, Linux)
python apkg2forms.py mazo.apkg  # línea de comandos -> mazo.gs
```
1. Abre el `.apkg`, elige los mazos y pulsa **Generar script**.
2. En https://script.google.com crea un proyecto, pega el `.gs`, elige `crearFormularios` y pulsa **Ejecutar**.
3. Los enlaces salen en el registro. Si quedan formularios, ejecútala otra vez.

## Requisitos
- Python 3.9+ con tkinter (Windows/macOS de python.org ya lo traen; Homebrew: `brew install python-tk`; Debian/Ubuntu: `sudo apt install python3-tk`).
- `.apkg` nuevos (zstd): Python 3.14+ o `pip install zstandard`; si no, exporta en Anki con "Compatible con versiones antiguas".

## Qué convierte
- **Tarjetas tipo test** (opciones `A.`/`a)` en el texto): la correcta se detecta por `Respuesta: C`, `c)`, opción en negrita o reverso con la opción.
- **Normales y cloze**: respuesta correcta + opciones falsas tomadas de otras tarjetas del mismo mazo.
- Se omiten (y se cuentan en el resumen) las tarjetas sin respuesta detectable o con respuesta larga. Las imágenes no se copian.

`python test_apkg2forms.py` comprueba el parser.

## Lanzar con doble clic
`Lanzar-macOS.command`, `Lanzar-Windows.bat` o `Lanzar-Linux.sh` (en Linux, si el gestor de archivos no los ejecuta: `chmod +x Lanzar-Linux.sh`). En macOS la primera vez: clic derecho > Abrir.

## Informe y extras
- Junto al `.gs` se crea `*.revisar.csv` con las tarjetas omitidas y las que tenían imagen.
- Las preguntas con imagen salen en el formulario con `[IMAGEN]` delante, y sus imágenes se copian a `*-imagenes/` con el nombre `formulario - pregunta N` (el CSV dice cuál es cuál), para añadirlas a mano.
- Si la tarjeta trae explicación, se muestra como feedback en el formulario.

## Ejecutable sin Python
- `./build.sh` genera `dist/apkg2forms.app` (macOS) o `dist/apkg2forms` (Linux). Hay que ejecutarlo en cada sistema.
- Para Windows, macOS y Linux a la vez: sube la carpeta a GitHub; `.github/workflows/build.yml` los compila y los deja en Actions > Artifacts.
- En macOS el `.app` no está firmado: la primera vez, clic derecho > Abrir.
