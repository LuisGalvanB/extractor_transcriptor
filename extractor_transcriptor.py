"""
Extractor de audio y transcriptor de video.

Este programa permite:
    1. Extraer el audio de un archivo local (video o audio).
    2. Descargar y extraer el audio de un video de YouTube.
    3. Descargar y extraer el audio de un video de Google Drive.
    4. Grabar la pantalla con audio del sistema y transcribir ese audio.

Posteriormente, el audio extraido puede transcribirse a texto
mediante Google Speech Recognition y guardarse en un archivo TXT.
"""

import os
import re
import sys
import time
import ctypes
import tempfile
import threading
import warnings
import subprocess
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuracion de FFmpeg y FFprobe.
# ---------------------------------------------------------------------------
RUTA_FFMPEG = r"C:\Users\COEM\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
RUTA_FFPROBE = r"C:\Users\COEM\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"

# Se agrega la carpeta de FFmpeg al PATH del proceso.
os.environ["PATH"] = (
    str(Path(RUTA_FFMPEG).parent)
    + os.pathsep
    + os.environ.get("PATH", "")
)

# Importaciones de terceros.
import gdown
import numpy as np
import soundcard as sc
import speech_recognition as sr
import mss
import cv2
from moviepy import VideoFileClip
from pydub import AudioSegment
from pytube import YouTube
from pytube.exceptions import PytubeError


# Silenciar avisos de discontinuidad de soundcard, que son normales
# cuando el sistema se queda momentaneamente sin buffers de audio.
warnings.filterwarnings(
    "ignore",
    category=Warning,
    module="soundcard"
)

# Silenciar el aviso de deprecacion de mss.mss.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module="mss"
)

# Configuracion de rutas para pydub.
AudioSegment.converter = RUTA_FFMPEG
AudioSegment.ffmpeg = RUTA_FFMPEG
AudioSegment.ffprobe = RUTA_FFPROBE


# Extensiones de archivo soportadas por la opcion 1.
EXTENSIONES_VIDEO_LOCAL = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v"
}
EXTENSIONES_AUDIO_LOCAL = {
    ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".wma"
}
EXTENSIONES_LOCAL_SOPORTADAS = EXTENSIONES_VIDEO_LOCAL | EXTENSIONES_AUDIO_LOCAL


def mantener_pc_despierto(activar=True):
    """
    Evita que Windows entre en suspension o apague la pantalla mientras
    se ejecuta una tarea larga (por ejemplo, transcribir un audio de
    muchos fragmentos o grabar la pantalla).

    Parametros:
        activar (bool): True para inhibir la suspension, False para
            devolver el control al sistema operativo.
    """
    if os.name != "nt":
        return

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    try:
        if activar:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:
        # Si por alguna razon falla, no se interrumpe la tarea principal.
        pass


def verificar_ffmpeg():
    """
    Verifica que FFmpeg y FFprobe esten instalados y accesibles.

    Lanza:
        FileNotFoundError: Si alguna de las rutas configuradas no existe.
    """
    ruta_ffmpeg = Path(RUTA_FFMPEG)
    ruta_ffprobe = Path(RUTA_FFPROBE)

    if not ruta_ffmpeg.exists():
        raise FileNotFoundError(
            f"No se encontro FFmpeg en: {ruta_ffmpeg}"
        )

    if not ruta_ffprobe.exists():
        raise FileNotFoundError(
            f"No se encontro FFprobe en: {ruta_ffprobe}"
        )


def limpiar_nombre_archivo(nombre):
    """
    Elimina caracteres no permitidos o problematicos para usar el texto
    como nombre de archivo.

    Parametros:
        nombre (str): Texto original que se desea usar como nombre de archivo.

    Retorna:
        str: Nombre de archivo limpio y seguro para el sistema de archivos.
             Si el resultado queda vacio, retorna "audio_extraido".
    """
    nombre_limpio = re.sub(r'[<>:"/\\|?*]', "_", nombre)
    nombre_limpio = re.sub(r"\s+", " ", nombre_limpio).strip()

    if not nombre_limpio:
        return "audio_extraido"

    return nombre_limpio


def limpiar_url(url):
    """
    Extrae una URL valida cuando el texto contiene etiquetas HTML
    o caracteres adicionales.

    Parametros:
        url (str): Cadena que puede contener una URL embebida.

    Retorna:
        str: URL limpia.

    Lanza:
        ValueError: Si no se encuentra una URL valida en el texto.
    """
    coincidencia = re.search(
        r'https?://[^\s"<]+',
        url
    )

    if not coincidencia:
        raise ValueError(
            "No se encontro una URL valida."
        )

    return coincidencia.group(0)


def solicitar_carpeta_salida():
    """
    Solicita al usuario una carpeta de salida.

    Si el usuario no escribe una ruta, se utiliza la carpeta actual
    de trabajo. Si la carpeta no existe, se intenta crear.

    Retorna:
        Path: Ruta absoluta de la carpeta de salida.

    Lanza:
        OSError: Si no es posible crear o acceder a la carpeta.
    """
    ruta_ingresada = input(
        "Ingrese la carpeta de salida o presione Enter para usar la carpeta actual: "
    ).strip()

    if ruta_ingresada:
        carpeta_salida = Path(ruta_ingresada).expanduser().resolve()
    else:
        carpeta_salida = Path.cwd()

    try:
        carpeta_salida.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OSError(
            f"No fue posible crear o acceder a la carpeta de salida: {error}"
        )

    return carpeta_salida


def convertir_audio_a_mp3_con_ffmpeg(ruta_entrada, ruta_salida):
    """
    Convierte cualquier archivo de audio a MP3 usando FFmpeg directamente
    por subprocess. Es mucho mas rapido y consume menos memoria que
    pydub para archivos grandes.

    Parametros:
        ruta_entrada (Path): Archivo de audio de origen.
        ruta_salida (Path): Ruta del MP3 a generar.

    Lanza:
        FileNotFoundError: Si FFmpeg no existe en la ruta configurada.
        RuntimeError: Si FFmpeg falla en la conversion.
    """
    if not Path(RUTA_FFMPEG).exists():
        raise FileNotFoundError(
            f"No se encontro FFmpeg en: {RUTA_FFMPEG}"
        )

    comando = [
        RUTA_FFMPEG,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(ruta_entrada),
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", "192k",
        str(ruta_salida),
    ]

    try:
        resultado = subprocess.run(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception as error:
        raise RuntimeError(
            f"No fue posible ejecutar FFmpeg para convertir el audio: {error}"
        )

    if resultado.returncode != 0:
        detalle = resultado.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(
            "FFmpeg fallo al convertir el audio. "
            f"Detalle: {detalle}"
        )

    if not ruta_salida.exists() or ruta_salida.stat().st_size == 0:
        raise RuntimeError(
            "FFmpeg no genero el archivo MP3 esperado."
        )


def extraer_audio_video_local(ruta_video, carpeta_salida):
    """
    Extrae el audio de un archivo local y lo guarda en MP3.

    - Si la entrada es un video, se usa MoviePy para extraer el audio.
    - Si la entrada ya es un MP3 que esta en la carpeta de salida,
      se devuelve tal cual sin convertirlo.
    - Si la entrada es otro formato de audio, se usa FFmpeg directamente
      para convertir a MP3 (mucho mas rapido que pydub).

    Parametros:
        ruta_video (str | Path): Ruta del archivo de entrada.
        carpeta_salida (Path): Carpeta donde se guardara el MP3 resultante.

    Retorna:
        Path: Ruta del archivo MP3 generado (o el mismo si ya era MP3).

    Lanza:
        FileNotFoundError: Si el archivo indicado no existe.
        ValueError: Si la ruta no es un archivo o no tiene una extension
                    soportada, o si el video no contiene pista de audio.
        RuntimeError: Si ocurre un error durante la extraccion del audio.
    """
    ruta_video = Path(ruta_video).expanduser().resolve()

    if not ruta_video.exists():
        raise FileNotFoundError(
            f"El archivo especificado no existe: {ruta_video}"
        )

    if not ruta_video.is_file():
        raise ValueError(
            f"La ruta especificada no corresponde a un archivo: {ruta_video}"
        )

    extension = ruta_video.suffix.lower()

    if extension not in EXTENSIONES_LOCAL_SOPORTADAS:
        raise ValueError(
            "Extension no soportada. Formatos validos: "
            + ", ".join(sorted(EXTENSIONES_LOCAL_SOPORTADAS))
        )

    # Si el archivo ya es MP3 y esta en la carpeta de salida,
    # se devuelve tal cual para no convertirlo innecesariamente.
    if extension == ".mp3" and ruta_video.parent == Path(carpeta_salida).resolve():
        print(
            "El archivo ya es MP3 y esta en la carpeta de salida. "
            "Se usara directamente para la transcripcion."
        )
        return ruta_video

    nombre_base = limpiar_nombre_archivo(ruta_video.stem)
    ruta_audio = Path(carpeta_salida) / f"{nombre_base}.mp3"

    # Si la salida coincidiria con la entrada, se busca otro nombre.
    if ruta_audio.resolve() == ruta_video.resolve():
        ruta_audio = Path(carpeta_salida) / f"{nombre_base}_convertido.mp3"

    # Si el archivo ya es audio (pero no MP3 o no esta en la carpeta),
    # se convierte directamente con FFmpeg.
    if extension in EXTENSIONES_AUDIO_LOCAL:
        print("El archivo ya es audio. Convirtiendo a MP3 con FFmpeg...")

        try:
            convertir_audio_a_mp3_con_ffmpeg(ruta_video, ruta_audio)
            return ruta_audio

        except Exception as error:
            if ruta_audio.exists():
                ruta_audio.unlink()
            raise RuntimeError(
                f"No fue posible convertir el audio a MP3: {error}"
            )

    # Si es video, se extrae el audio con MoviePy.
    video = None

    try:
        print("Abriendo el archivo de video...")
        video = VideoFileClip(str(ruta_video))

        if video.audio is None:
            raise ValueError(
                "El archivo de video no contiene una pista de audio. "
                "Si es una grabacion hecha por este programa, "
                "transcriba el archivo MP3 asociado en lugar del MP4."
            )

        print("Extrayendo y convirtiendo el audio a MP3...")

        video.audio.write_audiofile(
            str(ruta_audio),
            codec="libmp3lame",
            logger=None
        )

    except Exception as error:
        if ruta_audio.exists():
            ruta_audio.unlink()

        raise RuntimeError(
            f"No fue posible extraer el audio del video: {error}"
        )

    finally:
        if video is not None:
            try:
                if video.audio is not None:
                    video.audio.close()
                video.close()
            except Exception:
                pass

    return ruta_audio


def descargar_audio_youtube(url, carpeta_salida):
    """
    Descarga la mejor pista de audio disponible de un video de YouTube
    mediante Pytube y la convierte a formato MP3 utilizando Pydub.

    Parametros:
        url (str): URL completa del video de YouTube.
        carpeta_salida (Path): Carpeta donde se guardara el MP3 resultante.

    Retorna:
        Path: Ruta del archivo MP3 generado.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(
            "La URL proporcionada no es valida. Debe comenzar con http:// o https://"
        )

    try:
        print("Consultando la informacion del video de YouTube...")

        youtube = YouTube(url)
        titulo = limpiar_nombre_archivo(youtube.title or "audio_youtube")

        flujo_audio = (
            youtube.streams
            .filter(only_audio=True)
            .order_by("abr")
            .desc()
            .first()
        )

        if flujo_audio is None:
            raise RuntimeError(
                "No se encontro una pista de audio descargable."
            )

        ruta_audio_mp3 = carpeta_salida / f"{titulo}.mp3"

        with tempfile.TemporaryDirectory() as carpeta_temporal:
            print("Descargando la pista de audio...")

            archivo_descargado = flujo_audio.download(
                output_path=carpeta_temporal,
                filename="audio_original"
            )

            print("Convirtiendo el audio descargado a MP3...")

            audio = AudioSegment.from_file(archivo_descargado)

            audio.export(
                ruta_audio_mp3,
                format="mp3",
                bitrate="192k"
            )

        return ruta_audio_mp3

    except PytubeError as error:
        raise RuntimeError(
            f"Pytube no pudo descargar el video: {error}"
        )

    except OSError as error:
        raise RuntimeError(
            f"Ocurrio un error al guardar o convertir el archivo: {error}"
        )

    except Exception as error:
        raise RuntimeError(
            f"No fue posible procesar la URL de YouTube: {error}"
        )


def obtener_id_google_drive(url):
    """
    Extrae el identificador de un archivo desde una URL de Google Drive.

    Parametros:
        url (str): URL compartida del archivo de Google Drive.

    Retorna:
        str: Identificador del archivo.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(
            "La URL debe comenzar con http:// o https://"
        )

    if "drive.google.com" not in url:
        raise ValueError(
            "La URL proporcionada no corresponde a Google Drive."
        )

    patrones = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)"
    ]

    for patron in patrones:
        coincidencia = re.search(patron, url)

        if coincidencia:
            return coincidencia.group(1)

    raise ValueError(
        "No fue posible identificar el ID del archivo de Google Drive."
    )


def descargar_y_extraer_audio_google_drive(url, carpeta_salida):
    """
    Descarga temporalmente un video compartido desde Google Drive,
    extrae su pista de audio en formato MP3 y elimina el video temporal.

    Parametros:
        url (str): URL compartida del video de Google Drive.
        carpeta_salida (Path): Carpeta donde se guardara el archivo MP3.

    Retorna:
        Path: Ruta del archivo MP3 generado.
    """
    url = limpiar_url(url)
    id_archivo = obtener_id_google_drive(url)
    carpeta_salida = Path(carpeta_salida).resolve()

    nombre_temporal = f"google_drive_{id_archivo}.mp4"
    nombre_audio = f"clase_google_drive_{id_archivo}.mp3"
    ruta_audio = carpeta_salida / nombre_audio

    try:
        with tempfile.TemporaryDirectory() as carpeta_temporal:
            carpeta_temporal = Path(carpeta_temporal)
            ruta_video_temporal = carpeta_temporal / nombre_temporal

            print("Descargando el video desde Google Drive...")
            print("El tiempo de descarga dependera del tamano del archivo.")

            resultado = gdown.download(
                url=url,
                output=str(ruta_video_temporal),
                quiet=False,
                fuzzy=True
            )

            if resultado is None:
                raise PermissionError(
                    "Google Drive no permitio descargar el archivo. "
                    "Verifique que el enlace permita el acceso y la descarga."
                )

            if not ruta_video_temporal.exists():
                raise RuntimeError(
                    "La descarga termino, pero no se encontro el archivo temporal."
                )

            if ruta_video_temporal.stat().st_size == 0:
                raise RuntimeError(
                    "El archivo descargado esta vacio."
                )

            print("Video descargado correctamente.")
            print("Abriendo el video y extrayendo la pista de audio...")

            video = None

            try:
                video = VideoFileClip(str(ruta_video_temporal))

                if video.audio is None:
                    raise ValueError(
                        "El video de Google Drive no contiene una pista de audio."
                    )

                video.audio.write_audiofile(
                    str(ruta_audio),
                    codec="libmp3lame",
                    logger=None
                )

            finally:
                if video is not None:
                    try:
                        if video.audio is not None:
                            video.audio.close()

                        video.close()

                    except Exception:
                        pass

        if not ruta_audio.exists():
            raise RuntimeError(
                "No se genero el archivo MP3 esperado."
            )

        print("El video temporal fue eliminado.")
        return ruta_audio

    except PermissionError:
        raise

    except ValueError:
        raise

    except Exception as error:
        if ruta_audio.exists():
            try:
                ruta_audio.unlink()
            except OSError:
                pass

        raise RuntimeError(
            "No fue posible descargar o procesar el video de Google Drive. "
            f"Detalle: {error}"
        ) from error


def dividir_audio_en_fragmentos(audio, duracion_fragmento_ms=50000):
    """
    Divide un audio en fragmentos de duracion fija.

    Parametros:
        audio (AudioSegment): Audio completo que se desea dividir.
        duracion_fragmento_ms (int): Duracion de cada fragmento en milisegundos.

    Retorna:
        list[AudioSegment]: Lista con los fragmentos de audio.
    """
    fragmentos = []

    for inicio in range(0, len(audio), duracion_fragmento_ms):
        fin = min(inicio + duracion_fragmento_ms, len(audio))
        fragmentos.append(audio[inicio:fin])

    return fragmentos


def transcribir_audio(ruta_audio, idioma="es-CO"):
    """
    Convierte el archivo MP3 a fragmentos WAV temporales y transcribe
    cada fragmento mediante Google Speech Recognition.

    Guarda el progreso fragmento a fragmento en un archivo .parcial
    junto al audio, de modo que si el programa se interrumpe, al
    volver a ejecutarlo continuara desde el ultimo fragmento completado.

    Parametros:
        ruta_audio (str | Path): Ruta del archivo MP3 a transcribir.
        idioma (str): Codigo de idioma para el reconocimiento de voz.

    Retorna:
        str: Texto completo de la transcripcion.
    """
    ruta_audio = Path(ruta_audio).resolve()

    if not ruta_audio.exists():
        raise FileNotFoundError(
            f"El archivo de audio no existe: {ruta_audio}"
        )

    # Archivo de progreso (una linea por fragmento ya transcrito).
    ruta_progreso = ruta_audio.with_suffix(".parcial")

    mantener_pc_despierto(activar=True)

    reconocedor = sr.Recognizer()
    textos_reconocidos = []
    indice_inicio = 0

    # Se recuperan los fragmentos ya transcritos de una ejecucion previa.
    if ruta_progreso.exists():
        try:
            contenido = ruta_progreso.read_text(encoding="utf-8")
            for linea in contenido.split("\n"):
                if linea.startswith("### FRAGMENTO "):
                    textos_reconocidos.append(
                        linea.split("###", 2)[2].strip()
                    )
            indice_inicio = len(textos_reconocidos)
            if indice_inicio > 0:
                print(
                    f"Se encontro un progreso previo: "
                    f"{indice_inicio} fragmento(s) ya transcrito(s). "
                    f"Se continuara desde el fragmento {indice_inicio + 1}."
                )
        except OSError:
            # Si el archivo esta corrupto, se empieza desde cero.
            textos_reconocidos = []
            indice_inicio = 0

    try:
        print("Cargando el archivo MP3...")
        audio_mp3 = AudioSegment.from_file(ruta_audio, format="mp3")

        if len(audio_mp3) == 0:
            raise ValueError(
                "El archivo de audio esta vacio."
            )

        audio_normalizado = (
            audio_mp3
            .set_channels(1)
            .set_frame_rate(16000)
            .set_sample_width(2)
        )

        fragmentos = dividir_audio_en_fragmentos(audio_normalizado)
        total_fragmentos = len(fragmentos)

        print(
            f"El audio se procesara en {total_fragmentos} fragmento(s)."
        )

        with tempfile.TemporaryDirectory() as carpeta_temporal:
            carpeta_temporal = Path(carpeta_temporal)

            for numero, fragmento in enumerate(fragmentos, start=1):
                # Si ya se transcribio antes, se salta.
                if numero <= indice_inicio:
                    continue

                ruta_wav = carpeta_temporal / f"fragmento_{numero}.wav"

                fragmento.export(
                    ruta_wav,
                    format="wav"
                )

                print(
                    f"Transcribiendo fragmento {numero} de {total_fragmentos}..."
                )

                try:
                    with sr.AudioFile(str(ruta_wav)) as fuente:
                        datos_audio = reconocedor.record(fuente)

                    texto = reconocedor.recognize_google(
                        datos_audio,
                        language=idioma
                    )

                    texto_limpio = texto.strip()

                except sr.UnknownValueError:
                    texto_limpio = (
                        f"[Fragmento {numero}: no se pudo reconocer el contenido]"
                    )
                except sr.RequestError as error:
                    raise ConnectionError(
                        "No fue posible conectarse con Google Speech Recognition. "
                        f"Verifique la conexion a Internet. Detalle: {error}"
                    )

                textos_reconocidos.append(texto_limpio)

                # Se guarda el progreso inmediatamente despues de cada fragmento.
                try:
                    with ruta_progreso.open("a", encoding="utf-8") as archivo:
                        archivo.write(
                            f"### FRAGMENTO {numero} ### {texto_limpio}\n"
                        )
                except OSError:
                    pass

        transcripcion = "\n\n".join(textos_reconocidos).strip()

        if not transcripcion:
            raise RuntimeError(
                "La transcripcion no produjo ningun resultado."
            )

        # Si todo se completo, se elimina el archivo de progreso.
        try:
            if ruta_progreso.exists():
                ruta_progreso.unlink()
        except OSError:
            pass

        return transcripcion

    except FileNotFoundError:
        raise

    except ConnectionError:
        raise

    except Exception as error:
        raise RuntimeError(
            f"Ocurrio un error durante la transcripcion: {error}"
        )

    finally:
        mantener_pc_despierto(activar=False)


def guardar_transcripcion(transcripcion, ruta_audio):
    """
    Guarda la transcripcion en un archivo TXT con el mismo nombre base
    que el archivo de audio.

    Parametros:
        transcripcion (str): Texto resultante de la transcripcion.
        ruta_audio (str | Path): Ruta del archivo de audio de origen.

    Retorna:
        Path: Ruta del archivo TXT generado.
    """
    ruta_audio = Path(ruta_audio).resolve()
    ruta_texto = ruta_audio.with_suffix(".txt")

    try:
        ruta_texto.write_text(
            transcripcion,
            encoding="utf-8"
        )
    except OSError as error:
        raise OSError(
            f"No fue posible guardar la transcripcion: {error}"
        )

    return ruta_texto


# ===========================================================================
# Grabacion de pantalla con audio del sistema
# ===========================================================================

def obtener_altavoz_loopback():
    """
    Obtiene el dispositivo de loopback del altavoz predeterminado
    para capturar el audio del sistema.

    Retorna:
        soundcard._Speaker: Objeto de altavoz configurado como microfono.

    Lanza:
        RuntimeError: Si no se encuentra un dispositivo de loopback disponible.
    """
    try:
        altavoz = sc.default_speaker()
        if altavoz is None:
            raise RuntimeError(
                "No se encontro un altavoz predeterminado en el sistema."
            )

        microfono_loopback = sc.get_microphone(
            id=str(altavoz.name),
            include_loopback=True
        )

        if microfono_loopback is None:
            raise RuntimeError(
                "No fue posible obtener el dispositivo de loopback del altavoz. "
                "Verifique que su tarjeta de sonido permita la captura del audio del sistema."
            )

        return microfono_loopback

    except Exception as error:
        raise RuntimeError(
            "No fue posible inicializar la captura de audio del sistema. "
            f"Detalle: {error}"
        )


def abrir_proceso_ffmpeg_para_mp3(ruta_salida_mp3, frecuencia=44100, canales=2):
    """
    Abre un proceso de FFmpeg que lee audio PCM crudo por stdin y lo
    escribe comprimido como MP3 en la ruta indicada.

    Esto permite grabar directamente en MP3 sin pasar por un WAV
    intermedio, ahorrando disco y memoria.

    Parametros:
        ruta_salida_mp3 (Path): Ruta del archivo MP3 de salida.
        frecuencia (int): Frecuencia de muestreo del audio en Hz.
        canales (int): Cantidad de canales (1 mono, 2 estereo).

    Retorna:
        subprocess.Popen: Proceso de FFmpeg abierto con stdin disponible.

    Lanza:
        FileNotFoundError: Si FFmpeg no se encuentra en la ruta configurada.
        RuntimeError: Si el proceso no se puede iniciar.
    """
    if not Path(RUTA_FFMPEG).exists():
        raise FileNotFoundError(
            f"No se encontro FFmpeg en: {RUTA_FFMPEG}"
        )

    comando = [
        RUTA_FFMPEG,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "s16le",
        "-ar", str(frecuencia),
        "-ac", str(canales),
        "-i", "pipe:0",
        "-codec:a", "libmp3lame",
        "-b:a", "128k",
        str(ruta_salida_mp3),
    ]

    try:
        proceso = subprocess.Popen(
            comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except Exception as error:
        raise RuntimeError(
            f"No fue posible iniciar FFmpeg para grabar MP3: {error}"
        )

    return proceso


def grabar_pantalla_y_audio(
    carpeta_salida,
    duracion_segundos,
    fps=15,
    evento_detener=None
):
    """
    Graba la pantalla completa y el audio del sistema durante la
    cantidad de segundos indicada. Genera dos archivos:

        - Un video MP4 sin audio (captura de pantalla).
        - Un archivo MP3 con el audio del sistema, escrito directamente
          por FFmpeg en streaming (sin WAV intermedio).

    Parametros:
        carpeta_salida (Path): Carpeta donde se guardaran los archivos.
        duracion_segundos (int): Duracion maxima de la grabacion en segundos.
        fps (int): Cuadros por segundo de la captura de pantalla.
        evento_detener (threading.Event | None): Si se proporciona, el
            bucle de captura se detiene en cuanto el evento se active,
            antes de cumplir la duracion maxima.

    Retorna:
        tuple[Path, Path]: (ruta_video_mp4, ruta_audio_mp3)

    Lanza:
        ValueError: Si la duracion o el fps no son validos.
        RuntimeError: Si ocurre un error durante la grabacion.
    """
    if duracion_segundos <= 0:
        raise ValueError(
            "La duracion de la grabacion debe ser mayor que cero."
        )

    if fps <= 0:
        raise ValueError(
            "Los cuadros por segundo deben ser mayores que cero."
        )

    # Se inhibe la suspension de Windows durante toda la grabacion.
    mantener_pc_despierto(activar=True)

    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_base = f"grabacion_pantalla_{marca_tiempo}"

    ruta_video = carpeta_salida / f"{nombre_base}.mp4"
    ruta_audio_mp3 = carpeta_salida / f"{nombre_base}.mp3"

    frecuencia_muestreo = 44100
    canales = 2

    detener = threading.Event()
    audio_listo = threading.Event()
    errores = []

    def se_debe_detener(inicio):
        """
        Indica si la grabacion debe detenerse, ya sea porque se
        supero la duracion maxima o porque el usuario pulso el boton.
        """
        if detener.is_set():
            return True

        if evento_detener is not None and evento_detener.is_set():
            detener.set()
            return True

        if time.time() - inicio >= duracion_segundos:
            return True

        return False

    def capturar_audio():
        """
        Hilo encargado de capturar el audio del sistema y enviarlo
        directamente a FFmpeg por stdin para escribirlo como MP3.
        """
        proceso_ffmpeg = None
        try:
            microfono_loopback = obtener_altavoz_loopback()

            proceso_ffmpeg = abrir_proceso_ffmpeg_para_mp3(
                ruta_audio_mp3,
                frecuencia=frecuencia_muestreo,
                canales=canales
            )

            with microfono_loopback.recorder(
                samplerate=frecuencia_muestreo,
                channels=canales
            ) as grabador:
                tamano_bloque = 1024
                inicio = time.time()

                print("Capturando audio del sistema y comprimiendo a MP3...")

                while not detener.is_set():
                    bloque = grabador.record(numframes=tamano_bloque)

                    datos_int16 = np.int16(
                        np.clip(bloque, -1.0, 1.0) * 32767
                    )

                    try:
                        proceso_ffmpeg.stdin.write(datos_int16.tobytes())
                    except (BrokenPipeError, OSError):
                        break

                    if se_debe_detener(inicio):
                        break

                print("Audio del sistema guardado correctamente.")

        except Exception as error:
            errores.append(error)
            detener.set()

        finally:
            if proceso_ffmpeg is not None:
                try:
                    proceso_ffmpeg.stdin.close()
                except Exception:
                    pass

                try:
                    proceso_ffmpeg.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proceso_ffmpeg.kill()
                    proceso_ffmpeg.wait(timeout=5)

                if proceso_ffmpeg.returncode not in (0, None):
                    try:
                        error_ffmpeg = proceso_ffmpeg.stderr.read().decode(
                            "utf-8", errors="ignore"
                        )
                    except Exception:
                        error_ffmpeg = ""

                    if error_ffmpeg.strip():
                        errores.append(
                            RuntimeError(
                                "FFmpeg termino con error al escribir el MP3: "
                                + error_ffmpeg.strip()
                            )
                        )

            audio_listo.set()

    hilo_audio = threading.Thread(target=capturar_audio, daemon=True)
    hilo_audio.start()

    try:
        print(
            f"Grabando pantalla durante {duracion_segundos} segundos a {fps} fps..."
        )
        print("Puede pulsar el boton Detener en cualquier momento.")

        with mss.MSS() as capturador:
            monitor = capturador.monitors[0]
            ancho = monitor["width"]
            alto = monitor["height"]

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            escritor = cv2.VideoWriter(
                str(ruta_video),
                fourcc,
                fps,
                (ancho, alto)
            )

            if not escritor.isOpened():
                raise RuntimeError(
                    "No fue posible inicializar el escritor de video."
                )

            intervalo = 1.0 / fps
            inicio = time.time()

            try:
                while True:
                    if errores:
                        raise errores[0]

                    if se_debe_detener(inicio):
                        break

                    inicio_iteracion = time.time()

                    try:
                        fotograma = np.array(capturador.grab(monitor))
                    except Exception:
                        # Si BitBlt falla (pantalla bloqueada, cambio de
                        # resolucion, etc.), se espera un momento y se
                        # reintenta en el siguiente ciclo.
                        time.sleep(intervalo)
                        continue

                    fotograma_bgr = cv2.cvtColor(
                        fotograma,
                        cv2.COLOR_BGRA2BGR
                    )
                    escritor.write(fotograma_bgr)

                    tiempo_transcurrido = time.time() - inicio_iteracion
                    tiempo_restante = intervalo - tiempo_transcurrido
                    if tiempo_restante > 0:
                        time.sleep(tiempo_restante)

            except KeyboardInterrupt:
                print()
                print("Grabacion detenida por el usuario.")

            finally:
                escritor.release()

    except Exception as error:
        detener.set()
        audio_listo.wait(timeout=30)
        hilo_audio.join(timeout=5)
        mantener_pc_despierto(activar=False)
        raise RuntimeError(
            f"Ocurrio un error durante la grabacion de pantalla: {error}"
        )

    detener.set()
    audio_listo.wait(timeout=60)
    hilo_audio.join(timeout=10)

    if errores:
        mantener_pc_despierto(activar=False)
        raise RuntimeError(
            f"Error durante la captura de audio: {errores[0]}"
        )

    for _ in range(20):
        if ruta_audio_mp3.exists() and ruta_audio_mp3.stat().st_size > 0:
            break
        time.sleep(0.25)

    if not ruta_video.exists() or ruta_video.stat().st_size == 0:
        mantener_pc_despierto(activar=False)
        raise RuntimeError(
            "No se genero el archivo de video de la grabacion."
        )

    if not ruta_audio_mp3.exists() or ruta_audio_mp3.stat().st_size == 0:
        mantener_pc_despierto(activar=False)
        raise RuntimeError(
            "No se genero el archivo MP3 de audio de la grabacion."
        )

    print(f"Video de pantalla: {ruta_video}")
    print(f"Audio del sistema: {ruta_audio_mp3}")

    # Se libera la inhibicion de suspension.
    mantener_pc_despierto(activar=False)

    return ruta_video, ruta_audio_mp3


def procesar_grabacion_pantalla():
    """
    Solicita la duracion de la grabacion, captura la pantalla con el
    audio del sistema y devuelve la ruta del MP3 generado para que
    pueda transcribirse.

    Retorna:
        Path: Ruta del archivo MP3 con el audio del sistema.

    Lanza:
        ValueError: Si la duracion ingresada no es valida.
    """
    entrada = input(
        "Ingrese la duracion de la grabacion en segundos (por ejemplo 60): "
    ).strip()

    try:
        duracion = int(entrada)
    except ValueError:
        raise ValueError(
            "La duracion debe ser un numero entero de segundos."
        )

    if duracion <= 0:
        raise ValueError(
            "La duracion debe ser mayor que cero."
        )

    carpeta_salida = solicitar_carpeta_salida()

    print()
    print("Iniciando grabacion. Puede minimizar esta ventana si lo desea.")

    ruta_video, ruta_audio_mp3 = grabar_pantalla_y_audio(
        carpeta_salida,
        duracion_segundos=duracion
    )

    print(f"Video de pantalla guardado en: {ruta_video}")
    print(f"Audio del sistema guardado en: {ruta_audio_mp3}")

    return ruta_audio_mp3


def mostrar_menu():
    """
    Muestra las opciones disponibles en la consola.
    """
    print()
    print("=" * 60)
    print("EXTRACTOR DE AUDIO Y TRANSCRIPTOR DE VIDEO")
    print("=" * 60)
    print("1. Procesar un archivo local (video o audio)")
    print("2. Descargar y procesar un video de YouTube")
    print("3. Descargar y procesar un video de Google Drive")
    print("4. Grabar pantalla con audio del sistema y transcribir")
    print("5. Salir")
    print("=" * 60)


def procesar_archivo_local():
    """
    Solicita la informacion necesaria para procesar un archivo local.

    Retorna:
        Path: Ruta del archivo MP3 extraido.
    """
    ruta_video = input(
        "Ingrese la ruta completa del archivo local: "
    ).strip().strip('"')

    if not ruta_video:
        raise ValueError(
            "No se proporciono una ruta de archivo."
        )

    carpeta_salida = solicitar_carpeta_salida()

    ruta_audio = extraer_audio_video_local(
        ruta_video,
        carpeta_salida
    )

    print(f"Audio guardado en: {ruta_audio}")

    return ruta_audio


def procesar_video_youtube():
    """
    Solicita la URL y procesa un video alojado en YouTube.

    Retorna:
        Path: Ruta del archivo MP3 descargado.
    """
    url = input(
        "Ingrese la URL completa del video de YouTube: "
    ).strip()

    if not url:
        raise ValueError(
            "No se proporciono una URL."
        )

    carpeta_salida = solicitar_carpeta_salida()

    ruta_audio = descargar_audio_youtube(
        url,
        carpeta_salida
    )

    print(f"Audio guardado en: {ruta_audio}")

    return ruta_audio


def procesar_video_google_drive():
    """
    Solicita una URL de Google Drive, descarga temporalmente el video
    y extrae el audio en formato MP3.

    Retorna:
        Path: Ruta del archivo MP3 generado.
    """
    url = input(
        "Ingrese la URL completa del video de Google Drive: "
    ).strip()

    if not url:
        raise ValueError(
            "No se proporciono una URL de Google Drive."
        )

    url = limpiar_url(url)
    carpeta_salida = solicitar_carpeta_salida()

    ruta_audio = descargar_y_extraer_audio_google_drive(
        url,
        carpeta_salida
    )

    print(f"Audio guardado en: {ruta_audio}")

    return ruta_audio


def ejecutar_transcripcion(ruta_audio):
    """
    Transcribe el audio, muestra el resultado y lo almacena en TXT.

    Parametros:
        ruta_audio (Path): Ruta del archivo de audio a transcribir.
    """
    print()
    print("Iniciando transcripcion...")

    transcripcion = transcribir_audio(
        ruta_audio,
        idioma="es-CO"
    )

    ruta_texto = guardar_transcripcion(
        transcripcion,
        ruta_audio
    )

    print()
    print("=" * 60)
    print("TRANSCRIPCION")
    print("=" * 60)
    print(transcripcion)
    print("=" * 60)
    print(f"Transcripcion guardada en: {ruta_texto}")


def main():
    """
    Funcion principal del programa.

    Permite procesar:
        1. Archivos locales de video o audio.
        2. Videos de YouTube.
        3. Videos compartidos desde Google Drive.
        4. Grabaciones de pantalla con audio del sistema.
    """
    verificar_ffmpeg()

    while True:
        mostrar_menu()
        opcion = input("Seleccione una opcion: ").strip()

        try:
            if opcion == "1":
                ruta_audio = procesar_archivo_local()
                ejecutar_transcripcion(ruta_audio)

            elif opcion == "2":
                ruta_audio = procesar_video_youtube()
                ejecutar_transcripcion(ruta_audio)

            elif opcion == "3":
                ruta_audio = procesar_video_google_drive()
                ejecutar_transcripcion(ruta_audio)

            elif opcion == "4":
                ruta_audio = procesar_grabacion_pantalla()
                ejecutar_transcripcion(ruta_audio)

            elif opcion == "5":
                print("Programa finalizado.")
                break

            else:
                print(
                    "Opcion invalida. Seleccione 1, 2, 3, 4 o 5."
                )
                continue

        except FileNotFoundError as error:
            print(f"Error de archivo: {error}")

        except PermissionError as error:
            print(f"Error de permisos: {error}")

        except ValueError as error:
            print(f"Datos invalidos: {error}")

        except ConnectionError as error:
            print(f"Error de conexion: {error}")

        except KeyboardInterrupt:
            print()
            print("Operacion cancelada por el usuario.")

        except Exception as error:
            print(f"Error durante el procesamiento: {error}")

        print()
        input("Presione Enter para regresar al menu principal...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("Programa finalizado por el usuario.")
        sys.exit(0)