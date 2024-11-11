import serial
import time
import json
import paho.mqtt.client as mqtt
import ssl
from datetime import datetime

# Configuración ThingsBoard
THINGSBOARD_HOST = 'thingsboard.cloud'
ACCESS_TOKEN = 'pJnLZvLd57bLww2648gS'

# Configuración GPS
gps_serial = serial.Serial(
    port='/dev/ttyUSB0',
    baudrate=4800,
    timeout=1
)

# Configuración cliente MQTT
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(ACCESS_TOKEN)

# Configuración SSL/TLS
mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2)
mqtt_client.tls_insecure_set(False)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Conectado exitosamente a ThingsBoard")
    else:
        print(f"Error de conexión con código: {rc}")

def on_publish(client, userdata, mid):
    print(f"Datos publicados con éxito, id={mid}")

mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish

def convertir_a_decimal(grados, minutos, fraccion, direccion):
    """
    Convierte coordenadas de grados, minutos y fracción a formato decimal.
    Para Guatemala:
    - Latitud (N) debe ser positiva
    - Longitud (W) debe ser negativa
    """
    minutos_decimales = minutos + (fraccion / 1000.0)
    decimal = grados + (minutos_decimales / 60.0)
    
    # Invertir el signo para longitud W (oeste)
    if direccion == 'W':
        return -decimal
    # Mantener positivo para latitud N (norte)
    elif direccion == 'N':
        return decimal
    # Invertir para S (sur) y mantener positivo para E (este)
    elif direccion == 'S':
        return -decimal
    else:  # E (este)
        return decimal

def extraer_coordenadas(linea):
    try:
        # Primero procesamos la latitud
        lat_grados = int(linea[14:16])
        lat_minutos = int(linea[16:18])
        lat_fraccion = int(linea[18:21])
        lat_direccion = linea[21]

        # Luego procesamos la longitud
        lon_grados = int(linea[22:25])
        lon_minutos = int(linea[25:27])
        lon_fraccion = int(linea[27:30])
        lon_direccion = linea[30]

        # Convertimos ambas coordenadas
        lat_decimal = convertir_a_decimal(lat_grados, lat_minutos, lat_fraccion, lat_direccion)
        lon_decimal = convertir_a_decimal(lon_grados, lon_minutos, lon_fraccion, lon_direccion)

        # Verificación de los datos procesados
        print(f"Datos originales - Lat: {lat_grados}°{lat_minutos}'{lat_fraccion} {lat_direccion}, "
              f"Lon: {lon_grados}°{lon_minutos}'{lon_fraccion} {lon_direccion}")

        return lat_decimal, lon_decimal
    except ValueError as e:
        print(f"Error al extraer coordenadas: {e}")
        return None, None

def enviar_datos_thingsboard(latitude, longitude):
    telemetry = {
        'latitude': latitude,
        'longitude': longitude,
        'timestamp': int(time.time() * 1000)
    }
    
    try:
        mqtt_client.publish('v1/devices/me/telemetry', json.dumps(telemetry))
        print(f"Datos enviados: {telemetry}")
    except Exception as e:
        print(f"Error al enviar datos: {e}")

def leer_y_enviar_datos_gps():
    try:
        mqtt_client.connect(THINGSBOARD_HOST, 8883, 60)
        mqtt_client.loop_start()
        print("Intentando conectar a ThingsBoard...")
    except Exception as e:
        print(f"Error al conectar con ThingsBoard: {e}")
        return

    while True:
        if gps_serial.in_waiting > 0:
            try:
                linea = gps_serial.readline().decode('ascii', errors='replace').strip()

                if 'N' in linea and 'W' in linea:
                    lat_decimal, lon_decimal = extraer_coordenadas(linea)
                    
                    if lat_decimal is not None and lon_decimal is not None:
                        print(f"Latitud: {lat_decimal:.5f}, Longitud: {lon_decimal:.5f}")
                        enviar_datos_thingsboard(lat_decimal, lon_decimal)
            except Exception as e:
                print(f"Error al procesar datos GPS: {e}")
        else:
            time.sleep(1)

if __name__ == "__main__":
    try:
        leer_y_enviar_datos_gps()
    except KeyboardInterrupt:
        print("Programa interrumpido por el usuario")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        gps_serial.close()
        print("Conexiones cerradas correctamente")