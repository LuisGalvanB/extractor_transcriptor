Manual del programa
1. Estructura del proyecto
text
extractor_transcriptor/
├── .venv-1/                          Entorno virtual de Python
├── extractor_transcriptor.py         Núcleo: extrae audio y transcribe
├── extractor_transcriptor_gui.py     Interfaz gráfica (ventana tkinter)
└── interfaz_extractor.py             (Alias o versión alterna de la GUI)
Los dos archivos principales son:

extractor_transcriptor.py: la lógica del programa (extracción de audio, descarga, grabación de pantalla, transcripción).

extractor_transcriptor_gui.py: la ventana que reutiliza ese núcleo.

2. Activación del entorno virtual
Abre PowerShell en la carpeta del proyecto y activa el entorno antes de cualquier comando:

powershell
.\.venv-1\Scripts\Activate.ps1
Sabrás que está activo porque el prompt cambia a:

text
(.venv-1) PS C:\Users\COEM\extractor_transcriptor>
Si PowerShell bloquea la ejecución del script por políticas de seguridad, ejecuta una vez:

powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
3. Verificación de dependencias
Comprueba que todos los paquetes necesarios estén instalados:

powershell
python -c "import gdown; import moviepy; import pydub; import speech_recognition; import pytube; print('Dependencias correctas')"
Si falta alguno, instálalos con:

powershell
pip install gdown moviepy pydub SpeechRecognition pytube
Y los que se usan solo en la grabación de pantalla y la GUI:

powershell
pip install mss opencv-python soundcard numpy
tkinter no necesita instalación: viene incluido con Python en Windows.

4. Verificación de sintaxis
Antes de ejecutar, conviene comprobar que los archivos no tengan errores de escritura:

powershell
python -m py_compile extractor_transcriptor.py
python -m py_compile extractor_transcriptor_gui.py
python -m py_compile interfaz_extractor.py
Si un archivo compila bien, no imprime nada. Si hay un error de sintaxis, Python te muestra el archivo, la línea y el motivo.

5. Ejecución del programa
5.1 Modo consola (núcleo)
powershell
python extractor_transcriptor.py
Muestra un menú con las opciones:

text
1. Procesar un archivo local (video o audio)
2. Descargar y procesar un video de YouTube
3. Descargar y procesar un video de Google Drive
4. Grabar pantalla con audio del sistema y transcribir
5. Salir
Es la vía más directa si no necesitas ver progreso gráfico.

5.2 Modo ventana (interfaz gráfica)
powershell


O, si tienes el alias:

powershell
python extractor_transcriptor_gui.py

Se abre una ventana con las mismas opciones, campos para archivo, carpeta de salida, duración y FPS, y un área de progreso que muestra todo lo que el núcleo imprime en consola.

6. Flujo recomendado de uso
Activar el entorno

powershell
.\.venv-1\Scripts\Activate.ps1
Verificar dependencias

powershell
python -c "import gdown; import moviepy; import pydub; import speech_recognition; import pytube; print('Dependencias correctas')"
Verificar sintaxis (opcional, tras editar el código)

powershell
python -m py_compile extractor_transcriptor.py
python -m py_compile extractor_transcriptor_gui.py
Ejecutar la ventana

powershell
python extractor_transcriptor_gui.py
7. Uso de la ventana
Elige la tarea en la parte superior.

Rellena los campos:

Archivo local (tarea 1): usa el botón Examinar.

URL de YouTube (tarea 2) o URL de Google Drive (tarea 3): pégala directamente.

Duración en segundos y FPS (tarea 4): solo se habilitan para la grabación de pantalla.

Indica la carpeta de salida o deja la carpeta actual.

Pulsa Ejecutar.

Sigue el progreso en el área inferior. Al terminar verás un cuadro con las rutas del audio y del texto generados.

8. Requisitos externos
FFmpeg y FFprobe deben estar instalados y accesibles. Sus rutas están configuradas al inicio de extractor_transcriptor.py:

python
RUTA_FFMPEG = r"C:\Users\COEM\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
RUTA_FFPROBE = r"C:\Users\COEM\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"
Para verificar dónde están en tu equipo:

powershell
where.exe ffmpeg
where.exe ffprobe
Si la salida difiere, ajusta esas dos constantes.

Conexión a Internet para:

Descargar de YouTube (pytube).

Descargar de Google Drive (gdown).

Transcribir con Google Speech Recognition.

Tarjeta de sonido con loopback para la tarea 4. En Windows 10/11 funciona con el altavoz predeterminado.

9. Diagnóstico rápido de problemas
Síntoma	Causa probable	Solución
ModuleNotFoundError	Falta instalar un paquete en el entorno actual	Activa .venv-1 e instala lo que falte
No se encontró FFmpeg	Ruta mal configurada	Ejecuta where.exe ffmpeg y ajusta RUTA_FFMPEG
El archivo local debe tener extensión MP4	El núcleo antiguo solo aceptaba MP4	Usa la versión que acepta audio y video
No se generó el archivo MP3 en la tarea 4	El hilo de audio no había cerrado el MP3	Ya está resuelto con audio_listo y espera activa
Warnings data discontinuity in recording	Normal en soundcard cuando hay microcortes	Ya están silenciados con warnings.filterwarnings
pytube falla al descargar	YouTube cambia su API con frecuencia	Migrar a pytubefix si el problema persiste
10. Comandos resumidos (chuleta)
powershell
# Activar entorno
.\.venv-1\Scripts\Activate.ps1

# Verificar dependencias
python -c "import gdown; import moviepy; import pydub; import speech_recognition; import pytube; print('Dependencias correctas')"

# Validar sintaxis
python -m py_compile extractor_transcriptor.py
python -m py_compile extractor_transcriptor_gui.py
python -m py_compile interfaz_extractor.py

# Ejecutar consola
python extractor_transcriptor.py

# Ejecutar ventana
python extractor_transcriptor_gui.py
python interfaz_extractor.py


