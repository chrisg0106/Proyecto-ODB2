import obd
import time
from datetime import datetime
import csv
from pathlib import Path
from pytz import timezone
import tkinter as tk
from tkinter import ttk
import ttkthemes
from PIL import Image, ImageTk
import serial
import paho.mqtt.client as mqtt
import json
import ssl

# Configuración ThingsBoard
THINGSBOARD_HOST = 'thingsboard.cloud'
ACCESS_TOKEN = 'TU_ACCESS_TOKEN'  # Reemplaza con tu token de acceso

class VehicleMonitor:
    def __init__(self):
        # Inicializar conexión MQTT para ThingsBoard
        self.setup_thingsboard()
        
        print("Inicializando conexión OBD...")
        try:
            self.connection = obd.Async(portstr="/dev/rfcomm0", baudrate=38400)
            print(f"Estado de conexión: {self.connection.status()}")
        except Exception as e:
            print(f"Error al conectar: {str(e)}")
            return

        try:
            self.gps_serial = serial.Serial(
                port='/dev/ttyUSB0',
                baudrate=4800,
                timeout=1
            )
        except Exception as e:
            print(f"Error al inicializar GPS: {str(e)}")
            self.gps_serial = None

        self.tz = timezone('America/Guatemala')
        self.current_data = {
            'LATITUDE': 0.0,
            'LONGITUDE': 0.0
        }
        
        self.commands = [
            obd.commands.RPM,
            obd.commands.SPEED,
            obd.commands.ENGINE_LOAD,
            obd.commands.RUN_TIME,
            obd.commands.COOLANT_TEMP,
            obd.commands.INTAKE_TEMP,
            obd.commands.AMBIANT_AIR_TEMP,
            obd.commands.CATALYST_TEMP_B1S1,
            obd.commands.OIL_TEMP,
            obd.commands.FUEL_LEVEL,
            obd.commands.FUEL_RATE,
            obd.commands.FUEL_PRESSURE,
            obd.commands.ETHANOL_PERCENT,
            obd.commands.INTAKE_PRESSURE,
            obd.commands.BAROMETRIC_PRESSURE,
            obd.commands.MAF,
        ]
        
        self.setup_logger()
        self.watch_commands()

    def setup_thingsboard(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set(ACCESS_TOKEN)
        
        self.mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2)
        self.mqtt_client.tls_insecure_set(False)
        
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_publish = self.on_publish
        
        try:
            self.mqtt_client.connect(THINGSBOARD_HOST, 8883, 60)
            self.mqtt_client.loop_start()
            print("Conectado a ThingsBoard")
        except Exception as e:
            print(f"Error al conectar con ThingsBoard: {e}")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Conectado exitosamente a ThingsBoard")
        else:
            print(f"Error de conexión con ThingsBoard, código: {rc}")

    def on_publish(self, client, userdata, mid):
        print(f"Datos publicados en ThingsBoard, id={mid}")

    def convertir_a_decimal(self, grados, minutos, fraccion, direccion):
        minutos_decimales = minutos + (fraccion / 1000.0)
        decimal = grados + (minutos_decimales / 60.0)
        return abs(decimal) if direccion in ['N', 'S'] else decimal

    def send_to_thingsboard(self, latitude, longitude):
        try:
            telemetry = {
                'latitude': latitude,
                'longitude': longitude,
                'timestamp': int(time.time() * 1000)
            }
            self.mqtt_client.publish('v1/devices/me/telemetry', json.dumps(telemetry))
        except Exception as e:
            print(f"Error al enviar datos a ThingsBoard: {e}")

    def extraer_coordenadas(self, linea):
        try:
            lat_grados = int(linea[14:16])
            lat_minutos = int(linea[16:18])
            lat_fraccion = int(linea[18:21])
            lat_direccion = linea[21]
            
            lon_grados = int(linea[22:25])
            lon_minutos = int(linea[25:27])
            lon_fraccion = int(linea[27:30])
            lon_direccion = linea[30]
            
            lat_decimal = self.convertir_a_decimal(lat_grados, lat_minutos, lat_fraccion, lat_direccion)
            lon_decimal = self.convertir_a_decimal(lon_grados, lon_minutos, lon_fraccion, lon_direccion)
            
            self.current_data['LATITUDE'] = lat_decimal
            self.current_data['LONGITUDE'] = lon_decimal
            
            # Enviar datos a ThingsBoard
            self.send_to_thingsboard(lat_decimal, lon_decimal)
            
        except (ValueError, IndexError) as e:
            print(f"Error al extraer coordenadas: {e}")

    def read_gps(self):
        if self.gps_serial and self.gps_serial.in_waiting > 0:
            try:
                linea = self.gps_serial.readline().decode('ascii', errors='replace').strip()
                if 'N' in linea and 'W' in linea:
                    self.extraer_coordenadas(linea)
            except Exception as e:
                print(f"Error leyendo GPS: {str(e)}")

    def setup_logger(self):
        Path("vehicle_logs").mkdir(exist_ok=True)
        timestamp = datetime.now(self.tz).strftime("%y-%m-%d-%H-%M")
        self.log_file = f"vehicle_logs/vehicle-data-{timestamp}.csv"
        
        headers = ['Timestamp', 'Command', 'Value', 'Units']
        with open(self.log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    def log_data(self, command_name, value):
        timestamp = datetime.now(self.tz).strftime("%Y-%m-%d %H:%M:%S")
        units = value.units if hasattr(value, 'units') else ''
        value_str = str(value.magnitude) if hasattr(value, 'magnitude') else str(value)
        
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, command_name, value_str, units])

    def watch_commands(self):
        for cmd in self.commands:
            if self.connection.supports(cmd):
                self.connection.watch(cmd, callback=self.new_value_callback)
                print(f"Monitoreando {cmd.name}")

    def new_value_callback(self, response):
        if not response.is_null():
            self.current_data[response.command.name] = response.value
            self.log_data(response.command.name, response.value)

    def start(self):
        print("Iniciando monitoreo...")
        self.connection.start()

    def stop(self):
        print("Deteniendo monitoreo...")
        self.connection.stop()
        if self.gps_serial:
            self.gps_serial.close()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        print(f"Datos guardados en: {self.log_file}")

class OBDDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("UNIS OBDII SCANNER")
        self.root.geometry("1080x720")
        
        self.style = ttkthemes.ThemedStyle(self.root)
        self.style.set_theme("equilux")
        
        self.fonts = {
            'header': ("Helvetica", 24, "bold"),
            'panel_title': ("Helvetica", 16, "bold"),
            'label': ("Helvetica", 14),
            'value': ("Helvetica", 14, "bold"),
            'unit': ("Helvetica", 12),
            'footer': ("Helvetica", 12)
        }
        
        self.colors = {
            'bg': '#2E2E2E',
            'fg': '#FFFFFF',
            'highlight': '#007ACC',
            'warning': '#FFA500',
            'danger': '#FF4444',
            'success': '#00C851',
            'neutral': '#4B515D'
        }
        
        self.root.configure(bg=self.colors['bg'])
        self.value_labels = {}
        
        self.setup_gui()
        
        self.monitor = VehicleMonitor()
        self.monitor.start()
        
        self.update_dashboard()

    def setup_gui(self):
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill='x', padx=20, pady=10)

        try:
            logo_left = Image.open("logo_left.png")
            logo_left = logo_left.resize((80, 80), Image.Resampling.LANCZOS)
            self.logo_left_img = ImageTk.PhotoImage(logo_left)
            logo_left_label = ttk.Label(header_frame, image=self.logo_left_img)
            logo_left_label.pack(side=tk.LEFT, padx=10)
        except Exception as e:
            print(f"Error cargando logo izquierdo: {e}")

        title_label = ttk.Label(
            header_frame,
            text="UNIS OBDII SCANNER",
            font=self.fonts['header']
        )
        title_label.pack(side=tk.LEFT, expand=True)

        try:
            logo_right = Image.open("logo_right.png")
            logo_right = logo_right.resize((80, 80), Image.Resampling.LANCZOS)
            self.logo_right_img = ImageTk.PhotoImage(logo_right)
            logo_right_label = ttk.Label(header_frame, image=self.logo_right_img)
            logo_right_label.pack(side=tk.RIGHT, padx=10)
        except Exception as e:
            print(f"Error cargando logo derecho: {e}")

        main_container = ttk.Frame(self.root)
        main_container.pack(fill='both', expand=True, padx=20, pady=10)

        self.create_engine_panel(main_container)
        self.create_speed_panel(main_container)
        self.create_fuel_panel(main_container)
        self.create_temp_panel(main_container)
        self.create_gps_panel(main_container)

        main_container.grid_columnconfigure(0, weight=1)
        main_container.grid_columnconfigure(1, weight=1)
        main_container.grid_columnconfigure(2, weight=1)
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_rowconfigure(1, weight=1)

        self.create_footer()

    def create_panel(self, parent, title):
        panel = ttk.LabelFrame(parent, text=title, padding=15)
        panel.configure(style='Custom.TLabelframe')
        self.style.configure(
            'Custom.TLabelframe.Label',
            font=self.fonts['panel_title']
        )
        return panel

    def add_data_row(self, parent, key, label, unit, row):
        ttk.Label(
            parent,
            text=f"{label}:",
            font=self.fonts['label']
        ).grid(row=row, column=0, padx=5, pady=5, sticky='w')
        
        value_label = ttk.Label(
            parent,
            text="--",
            font=self.fonts['value']
        )
        value_label.grid(row=row, column=1, padx=5, pady=5, sticky='e')
        
        ttk.Label(
            parent,
            text=unit,
            font=self.fonts['unit']
        ).grid(row=row, column=2, padx=(2, 5), pady=5, sticky='w')
        
        self.value_labels[key] = value_label
        parent.grid_columnconfigure(1, weight=1)

    def create_engine_panel(self, parent):
        panel = self.create_panel(parent, "Motor")
        self.add_data_row(panel, "RPM", "RPM", "rpm", 0)
        self.add_data_row(panel, "ENGINE_LOAD", "Carga", "%", 1)
        self.add_data_row(panel, "COOLANT_TEMP", "Refrigerante", "°C", 2)
        panel.grid(row=0, column=0, padx=10, pady=10, sticky='nsew')

    def create_speed_panel(self, parent):
        panel = self.create_panel(parent, "Velocidad y Presión")
        self.add_data_row(panel, "SPEED", "Velocidad", "km/h", 0)
        self.add_data_row(panel, "INTAKE_PRESSURE", "Presión Adm.", "kPa", 1)
        self.add_data_row(panel, "BAROMETRIC_PRESSURE", "Presión Bar.", "kPa", 2)
        panel.grid(row=0, column=1, padx=10, pady=10, sticky='nsew')

    def create_fuel_panel(self, parent):
        panel = self.create_panel(parent, "Combustible")
        self.add_data_row(panel, "FUEL_LEVEL", "Nivel", "%", 0)
        self.add_data_row(panel, "FUEL_RATE", "Consumo", "L/h", 1)
        self.add_data_row(panel, "FUEL_PRESSURE", "Presión", "kPa", 2)
        self.add_data_row(panel, "ETHANOL_PERCENT", "Etanol", "%", 3)
        panel.grid(row=0, column=2, padx=10, pady=10, sticky='nsew')

    def create_temp_panel(self, parent):
        panel = self.create_panel(parent, "Temperaturas")
        self.add_data_row(panel, "INTAKE_TEMP", "Admisión", "°C", 0)
        self.add_data_row(panel, "AMBIANT_AIR_TEMP", "Ambiente", "°C", 1)
        self.add_data_row(panel, "OIL_TEMP", "Aceite", "°C", 2)
        self.add_data_row(panel, "CATALYST_TEMP_B1S1", "Catalizador", "°C", 3)
        panel.grid(row=1, column=0, padx=10, pady=10, sticky='nsew')

    def create_gps_panel(self, parent):
        panel = self.create_panel(parent, "Ubicación GPS")
        self.add_data_row(panel, "LATITUDE", "Latitud", "°", 0)
        self.add_data_row(panel, "LONGITUDE", "Longitud", "°", 1)
        panel.grid(row=1, column=1, columnspan=2, padx=10, pady=10, sticky='nsew')

    def create_footer(self):
        self.timestamp_label = ttk.Label(
            self.root,
            text="Última actualización: --:--:--",
            font=self.fonts['footer']
        )
        self.timestamp_label.pack(pady=10)

        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10)
        
        ttk.Button(
            control_frame,
            text="Detener",
            command=self.stop_monitoring
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            control_frame,
            text="Reiniciar",
            command=self.restart_monitoring
        ).pack(side=tk.LEFT, padx=5)

    def update_dashboard(self):
        try:
            # Leer datos GPS
            self.monitor.read_gps()
            
            # Actualizar timestamp
            current_time = datetime.now(self.monitor.tz).strftime("%Y-%m-%d %H:%M:%S")
            self.timestamp_label.configure(text=f"Última actualización: {current_time}")
            
            # Actualizar valores
            for command_name, value in self.monitor.current_data.items():
                if command_name in self.value_labels:
                    if isinstance(value, (int, float)):
                        display_value = f"{value:.5f}"
                    elif hasattr(value, 'magnitude'):
                        display_value = f"{value.magnitude:.1f}"
                    else:
                        display_value = str(value)
                    self.value_labels[command_name].configure(text=display_value)
            
            # Programar siguiente actualización
            self.root.after(1000, self.update_dashboard)
            
        except Exception as e:
            print(f"Error actualizando dashboard: {str(e)}")

    def stop_monitoring(self):
        try:
            self.monitor.stop()
        except Exception as e:
            print(f"Error al detener: {str(e)}")

    def restart_monitoring(self):
        try:
            self.monitor = VehicleMonitor()
            self.monitor.start()
        except Exception as e:
            print(f"Error al reiniciar: {str(e)}")

def main():
    try:
        root = tk.Tk()
        app = OBDDashboard(root)
        root.mainloop()
    except Exception as e:
        print(f"Error en la aplicación: {str(e)}")

if __name__ == "__main__":
    main()
