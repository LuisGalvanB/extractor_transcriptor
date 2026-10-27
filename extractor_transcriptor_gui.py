"""
Interfaz grafica para el extractor y transcriptor de audio.

Esta aplicacion reutiliza las funciones del archivo
extractor_transcriptor.py y permite:
    1. Procesar archivos locales de video o audio.
    2. Descargar y procesar videos de YouTube.
    3. Descargar y procesar videos de Google Drive.
    4. Grabar la pantalla con audio del sistema.
    5. Transcribir el audio y guardar el resultado en TXT.

Requisitos:
    - extractor_transcriptor.py debe estar en la misma carpeta.
    - Las dependencias del archivo principal deben estar instaladas.
    - FFmpeg y FFprobe deben estar configurados en el archivo principal.
"""

import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


try:
    import extractor_transcriptor as nucleo
except Exception as error_importacion:
    print("No fue posible importar extractor_transcriptor.py")
    print(f"Detalle: {error_importacion}")
    raise


class RedireccionSalida:
    """Redirige texto escrito en stdout o stderr hacia una cola."""

    def __init__(self, cola):
        self.cola = cola

    def write(self, mensaje):
        if mensaje:
            self.cola.put(("log", mensaje))
        return len(mensaje) if mensaje else 0

    def flush(self):
        pass

    def isatty(self):
        return False


class AplicacionExtractor:
    """Ventana principal de la aplicacion."""

    def __init__(self, raiz):
        self.raiz = raiz
        self.raiz.title("Extractor de audio y transcriptor de video")
        self.raiz.geometry("920x720")
        self.raiz.minsize(800, 600)

        self.cola = queue.Queue()
        self.hilo_trabajo = None
        self.tarea_en_curso = False

        # Evento para pedir al nucleo que detenga la grabacion de pantalla.
        self.evento_detener_grabacion = None

        self._construir_interfaz()
        self.raiz.after(100, self._procesar_cola)
        self.raiz.protocol("WM_DELETE_WINDOW", self._al_cerrar_ventana)

    def _construir_interfaz(self):
        """Construye los controles de la ventana."""
        marco_superior = ttk.LabelFrame(self.raiz, text="Tarea a realizar")
        marco_superior.pack(fill="x", padx=10, pady=(10, 5))

        self.variable_tarea = tk.StringVar(value="1")
        opciones = [
            ("1", "Procesar un archivo local de video o audio"),
            ("2", "Descargar y procesar un video de YouTube"),
            ("3", "Descargar y procesar un video de Google Drive"),
            ("4", "Grabar pantalla con audio del sistema"),
        ]

        for valor, etiqueta in opciones:
            ttk.Radiobutton(
                marco_superior,
                text=etiqueta,
                value=valor,
                variable=self.variable_tarea,
                command=self._al_cambiar_tarea,
            ).pack(anchor="w", padx=10, pady=2)

        self.marco_parametros = ttk.LabelFrame(self.raiz, text="Parametros")
        self.marco_parametros.pack(fill="x", padx=10, pady=5)
        self.marco_parametros.columnconfigure(1, weight=1)

        self.variable_etiqueta_entrada = tk.StringVar(value="Archivo local:")
        ttk.Label(
            self.marco_parametros,
            textvariable=self.variable_etiqueta_entrada,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        self.variable_entrada = tk.StringVar()
        self.campo_entrada = ttk.Entry(
            self.marco_parametros,
            textvariable=self.variable_entrada,
            width=70,
        )
        self.campo_entrada.grid(row=0, column=1, sticky="we", padx=6, pady=6)

        self.boton_examinar = ttk.Button(
            self.marco_parametros,
            text="Examinar...",
            command=self._seleccionar_archivo,
        )
        self.boton_examinar.grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(
            self.marco_parametros,
            text="Carpeta de salida:",
        ).grid(row=1, column=0, sticky="w", padx=8, pady=6)

        self.variable_salida = tk.StringVar(value=str(Path.cwd()))
        self.campo_salida = ttk.Entry(
            self.marco_parametros,
            textvariable=self.variable_salida,
            width=70,
        )
        self.campo_salida.grid(row=1, column=1, sticky="we", padx=6, pady=6)

        self.boton_salida = ttk.Button(
            self.marco_parametros,
            text="Elegir...",
            command=self._seleccionar_carpeta_salida,
        )
        self.boton_salida.grid(row=1, column=2, padx=6, pady=6)

        ttk.Label(
            self.marco_parametros,
            text="Duracion en segundos:",
        ).grid(row=2, column=0, sticky="w", padx=8, pady=6)

        self.variable_duracion = tk.StringVar(value="60")
        self.campo_duracion = ttk.Entry(
            self.marco_parametros,
            textvariable=self.variable_duracion,
            width=12,
        )
        self.campo_duracion.grid(row=2, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(
            self.marco_parametros,
            text="Cuadros por segundo (FPS):",
        ).grid(row=3, column=0, sticky="w", padx=8, pady=6)

        self.variable_fps = tk.StringVar(value="10")
        self.campo_fps = ttk.Entry(
            self.marco_parametros,
            textvariable=self.variable_fps,
            width=12,
        )
        self.campo_fps.grid(row=3, column=1, sticky="w", padx=6, pady=6)

        marco_botones = ttk.Frame(self.raiz)
        marco_botones.pack(fill="x", padx=10, pady=5)

        self.boton_ejecutar = ttk.Button(
            marco_botones,
            text="Ejecutar",
            command=self._al_ejecutar,
        )
        self.boton_ejecutar.pack(side="left", padx=5)

        self.boton_limpiar = ttk.Button(
            marco_botones,
            text="Limpiar registro",
            command=self._limpiar_registro,
        )
        self.boton_limpiar.pack(side="left", padx=5)

        self.boton_detener = ttk.Button(
            marco_botones,
            text="Detener grabacion y transcribir",
            command=self._al_detener_grabacion,
            state="disabled",
        )
        self.boton_detener.pack(side="left", padx=5)

        self.barra_progreso = ttk.Progressbar(
            marco_botones,
            mode="indeterminate",
            length=220,
        )
        self.barra_progreso.pack(side="right", padx=5)

        marco_registro = ttk.LabelFrame(self.raiz, text="Progreso")
        marco_registro.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.area_registro = scrolledtext.ScrolledText(
            marco_registro,
            wrap="word",
            height=20,
            state="disabled",
            font=("Consolas", 9),
        )
        self.area_registro.pack(fill="both", expand=True, padx=5, pady=5)

        self.variable_estado = tk.StringVar(value="Listo.")
        ttk.Label(
            self.raiz,
            textvariable=self.variable_estado,
            anchor="w",
            relief="sunken",
        ).pack(fill="x", side="bottom")

        self._al_cambiar_tarea()

    def _al_cambiar_tarea(self):
        """Ajusta los campos de acuerdo con la tarea seleccionada."""
        tarea = self.variable_tarea.get()

        if tarea == "1":
            self.variable_etiqueta_entrada.set("Archivo local:")
            self.campo_entrada.configure(state="normal")
            self.boton_examinar.configure(state="normal")
            self.campo_duracion.configure(state="disabled")
            self.campo_fps.configure(state="disabled")
        elif tarea == "2":
            self.variable_etiqueta_entrada.set("URL de YouTube:")
            self.campo_entrada.configure(state="normal")
            self.boton_examinar.configure(state="disabled")
            self.campo_duracion.configure(state="disabled")
            self.campo_fps.configure(state="disabled")
        elif tarea == "3":
            self.variable_etiqueta_entrada.set("URL de Google Drive:")
            self.campo_entrada.configure(state="normal")
            self.boton_examinar.configure(state="disabled")
            self.campo_duracion.configure(state="disabled")
            self.campo_fps.configure(state="disabled")
        else:
            self.variable_etiqueta_entrada.set("Entrada no requerida:")
            self.campo_entrada.configure(state="disabled")
            self.boton_examinar.configure(state="disabled")
            self.campo_duracion.configure(state="normal")
            self.campo_fps.configure(state="normal")

    def _seleccionar_archivo(self):
        """Abre el selector de archivos locales."""
        ruta = filedialog.askopenfilename(
            title="Seleccione un archivo de video o audio",
            filetypes=[
                (
                    "Archivos de video o audio",
                    "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.m4v "
                    "*.wav *.mp3 *.m4a *.aac *.ogg *.flac *.wma",
                ),
                ("Todos los archivos", "*.*"),
            ],
        )
        if ruta:
            self.variable_entrada.set(ruta)

    def _seleccionar_carpeta_salida(self):
        """Abre el selector de carpeta de salida."""
        carpeta = filedialog.askdirectory(title="Seleccione la carpeta de salida")
        if carpeta:
            self.variable_salida.set(carpeta)

    def _limpiar_registro(self):
        """Borra el registro de progreso."""
        self.area_registro.configure(state="normal")
        self.area_registro.delete("1.0", "end")
        self.area_registro.configure(state="disabled")

    def _escribir_log(self, texto):
        """Agrega texto al registro y desplaza la vista al final."""
        self.area_registro.configure(state="normal")
        self.area_registro.insert("end", texto)
        self.area_registro.see("end")
        self.area_registro.configure(state="disabled")

    def _al_cerrar_ventana(self):
        """Impide cerrar la aplicacion durante una tarea activa."""
        if self.tarea_en_curso:
            messagebox.showwarning(
                "Tarea en curso",
                "Debe esperar a que termine la tarea antes de cerrar la aplicacion.",
            )
            return
        self.raiz.destroy()

    def _cambiar_estado_controles(self, ejecutando, tarea=None):
        """
        Activa o desactiva controles durante una tarea.

        Parametros:
            ejecutando (bool): True si hay una tarea en curso.
            tarea (str | None): Identificador de la tarea actual. Se usa
                para saber si hay que habilitar el boton de detener
                grabacion (solo en la tarea 4).
        """
        self.tarea_en_curso = ejecutando
        estado = "disabled" if ejecutando else "normal"

        self.boton_ejecutar.configure(state=estado)
        self.boton_limpiar.configure(state=estado)
        self.boton_salida.configure(state=estado)

        if ejecutando:
            self.barra_progreso.start(12)

            # El boton Detener solo se habilita en la tarea 4.
            if tarea == "4":
                self.boton_detener.configure(state="normal")
            else:
                self.boton_detener.configure(state="disabled")
        else:
            self.barra_progreso.stop()
            self.boton_detener.configure(state="disabled")
            self.evento_detener_grabacion = None
            self._al_cambiar_tarea()

    def _al_ejecutar(self):
        """Valida los datos y lanza la tarea en un hilo secundario."""
        if self.tarea_en_curso:
            messagebox.showinfo("Espere", "Ya hay una tarea en ejecucion.")
            return

        try:
            tarea, entrada, carpeta_salida, duracion, fps = self._validar_entradas()
        except (ValueError, OSError) as error:
            messagebox.showerror("Datos invalidos", str(error))
            return

        # Se prepara el evento para poder detener la grabacion si aplica.
        if tarea == "4":
            self.evento_detener_grabacion = threading.Event()
        else:
            self.evento_detener_grabacion = None

        self._cambiar_estado_controles(True, tarea)
        self.variable_estado.set("Ejecutando...")
        self._escribir_log(
            "\n" + "=" * 60 + "\n"
            + f"Inicio de tarea: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            + "=" * 60 + "\n"
        )

        self.hilo_trabajo = threading.Thread(
            target=self._ejecutar_tarea,
            args=(tarea, entrada, carpeta_salida, duracion, fps),
            daemon=True,
        )
        self.hilo_trabajo.start()

    def _al_detener_grabacion(self):
        """
        Se ejecuta cuando el usuario pulsa el boton Detener durante
        la tarea de grabacion de pantalla. Activa el evento que el
        nucleo consulta para terminar antes de la duracion maxima.
        """
        if self.evento_detener_grabacion is not None:
            self.evento_detener_grabacion.set()
            self.variable_estado.set(
                "Deteniendo grabacion. Se iniciara la transcripcion en breve..."
            )
            self.boton_detener.configure(state="disabled")
            self._escribir_log(
                "\n[INFO] Se solicito detener la grabacion. "
                "Se guardara el audio capturado hasta este momento "
                "y se iniciara la transcripcion.\n"
            )

    def _validar_entradas(self):
        """Valida campos y devuelve los parametros normalizados."""
        tarea = self.variable_tarea.get()
        entrada = self.variable_entrada.get().strip().strip('"').strip("'")
        carpeta_texto = self.variable_salida.get().strip().strip('"')

        if not carpeta_texto:
            raise ValueError("Debe indicar una carpeta de salida.")

        carpeta_salida = Path(carpeta_texto).expanduser().resolve()
        carpeta_salida.mkdir(parents=True, exist_ok=True)

        duracion = None
        fps = None

        if tarea == "1":
            if not entrada:
                raise ValueError("Debe seleccionar un archivo local.")
            ruta = Path(entrada).expanduser().resolve()
            if not ruta.exists():
                raise ValueError(f"El archivo no existe: {ruta}")
            if not ruta.is_file():
                raise ValueError("La ruta seleccionada no corresponde a un archivo.")
            entrada = str(ruta)

        elif tarea == "2":
            if not entrada:
                raise ValueError("Debe ingresar una URL de YouTube.")
            entrada = nucleo.limpiar_url(entrada)
            if "youtube.com" not in entrada and "youtu.be" not in entrada:
                raise ValueError("La URL no corresponde a YouTube.")

        elif tarea == "3":
            if not entrada:
                raise ValueError("Debe ingresar una URL de Google Drive.")
            entrada = nucleo.limpiar_url(entrada)
            if "drive.google.com" not in entrada:
                raise ValueError("La URL no corresponde a Google Drive.")

        elif tarea == "4":
            try:
                duracion = int(self.variable_duracion.get().strip())
            except ValueError as error:
                raise ValueError(
                    "La duracion debe ser un numero entero de segundos."
                ) from error
            if duracion <= 0:
                raise ValueError("La duracion debe ser mayor que cero.")

            try:
                fps = int(self.variable_fps.get().strip())
            except ValueError as error:
                raise ValueError(
                    "Los FPS deben ser un numero entero."
                ) from error
            if fps <= 0 or fps > 60:
                raise ValueError(
                    "Los FPS deben estar entre 1 y 60."
                )
        else:
            raise ValueError(f"Tarea desconocida: {tarea}")

        return tarea, entrada, carpeta_salida, duracion, fps

    def _ejecutar_tarea(self, tarea, entrada, carpeta_salida, duracion, fps):
        """Ejecuta la tarea sin bloquear el hilo principal de Tkinter."""
        salida_original = sys.stdout
        error_original = sys.stderr
        redireccion = RedireccionSalida(self.cola)
        sys.stdout = redireccion
        sys.stderr = redireccion

        ruta_video = None

        try:
            nucleo.verificar_ffmpeg()

            if tarea == "1":
                ruta_audio = nucleo.extraer_audio_video_local(
                    entrada, carpeta_salida
                )
            elif tarea == "2":
                ruta_audio = nucleo.descargar_audio_youtube(
                    entrada, carpeta_salida
                )
            elif tarea == "3":
                ruta_audio = nucleo.descargar_y_extraer_audio_google_drive(
                    entrada, carpeta_salida
                )
            elif tarea == "4":
                self.cola.put(
                    (
                        "log",
                        "\nIniciando grabacion. "
                        "Puede minimizar esta ventana si lo desea.\n"
                        "Pulse el boton Detener para terminar antes de tiempo.\n",
                    )
                )
                ruta_video, ruta_audio = nucleo.grabar_pantalla_y_audio(
                    carpeta_salida,
                    duracion_segundos=duracion,
                    fps=fps,
                    evento_detener=self.evento_detener_grabacion,
                )
            else:
                raise ValueError(f"Tarea desconocida: {tarea}")

            self.cola.put(("log", f"\nAudio disponible en: {ruta_audio}\n"))
            if ruta_video is not None:
                self.cola.put(("log", f"Video disponible en: {ruta_video}\n"))

            self.cola.put(("log", "\nIniciando transcripcion...\n"))
            transcripcion = nucleo.transcribir_audio(ruta_audio, idioma="es-CO")
            ruta_texto = nucleo.guardar_transcripcion(transcripcion, ruta_audio)

            self.cola.put(
                (
                    "log",
                    "\n" + "=" * 60 + "\n"
                    + "TRANSCRIPCION\n"
                    + "=" * 60 + "\n"
                    + transcripcion + "\n"
                    + "=" * 60 + "\n"
                    + f"Transcripcion guardada en: {ruta_texto}\n",
                )
            )
            self.cola.put(
                ("fin", ("ok", ruta_audio, ruta_texto, ruta_video))
            )

        except Exception as error:
            detalle = traceback.format_exc()
            self.cola.put(("log", f"\n[ERROR] {error}\n{detalle}\n"))
            self.cola.put(("fin", ("error", error, None, ruta_video)))
        finally:
            sys.stdout = salida_original
            sys.stderr = error_original

    def _procesar_cola(self):
        """Procesa mensajes producidos por el hilo secundario."""
        try:
            while True:
                tipo, contenido = self.cola.get_nowait()
                if tipo == "log":
                    self._escribir_log(contenido)
                elif tipo == "fin":
                    self._al_terminar_tarea(contenido)
        except queue.Empty:
            pass

        if self.raiz.winfo_exists():
            self.raiz.after(100, self._procesar_cola)

    def _al_terminar_tarea(self, resultado):
        """Restaura la interfaz y muestra el resultado final."""
        self._cambiar_estado_controles(False)
        estado, dato1, dato2, ruta_video = resultado

        if estado == "ok":
            self.variable_estado.set(f"Tarea completada. Transcripcion: {dato2}")
            mensaje = (
                "El proceso termino correctamente.\n\n"
                f"Audio: {dato1}\n"
                f"Transcripcion: {dato2}"
            )
            if ruta_video is not None:
                mensaje += f"\nVideo: {ruta_video}"
            messagebox.showinfo("Tarea completada", mensaje)
        else:
            self.variable_estado.set(f"Error: {dato1}")
            messagebox.showerror("Error durante el procesamiento", str(dato1))


def main():
    """Inicia la interfaz grafica y valida FFmpeg."""
    raiz = tk.Tk()
    raiz.withdraw()

    try:
        nucleo.verificar_ffmpeg()
    except Exception as error:
        messagebox.showerror(
            "Error de configuracion",
            "No fue posible validar FFmpeg y FFprobe.\n\n"
            f"Detalle: {error}",
        )
        raiz.destroy()
        return

    try:
        estilo = ttk.Style(raiz)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
    except Exception:
        pass

    AplicacionExtractor(raiz)
    raiz.deiconify()
    raiz.mainloop()


if __name__ == "__main__":
    main()