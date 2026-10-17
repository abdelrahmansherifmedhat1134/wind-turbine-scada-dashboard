#include <WiFi.h>
#include <Wire.h>
#include <MPU6050.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASSWORD, PI_SERVER_IP (copy secrets.example.h)

MPU6050 mpu;

// --- WiFi setup ---
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* serverIP = PI_SERVER_IP;
const uint16_t serverPort = 6000;
WiFiClient client;

// --- Variables ---
double yaw_est = 0.0;        // fused yaw (degrees, unwrapped)
double gyroZ_offset = 0.0;   // raw units bias
unsigned long lastMicros = 0;

// --- Tuning ---
const double GYRO_SENS_250 = 131.0; // LSB per deg/s for ±250 dps
const double LPF_BETA = 0.1;        // Low-pass filter factor
double gyro_lpf = 0.0;

void hardCalibrateGyroZ(int samples = 2000) {
  long sum = 0;
  for (int i = 0; i < samples; ++i) {
    int16_t ax, ay, az, gx, gy, gz;
    mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
    sum += gz;
    delay(1);
  }
  gyroZ_offset = sum / (double)samples;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22); // SDA=21, SCL=22 for ESP32
  mpu.initialize();

  if (!mpu.testConnection()) {
    Serial.println("❌ MPU6050 connection failed!");
    while (1);
  }
  Serial.println("✅ MPU6050 connected");

  delay(2000); // warm up
  hardCalibrateGyroZ();
  Serial.println("✅ Gyro calibrated");

  lastMicros = micros();

  // --- Connect WiFi ---
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" connected!");

  // --- Connect to Raspberry Pi ---
  Serial.print("Connecting to server...");
  while (!client.connect(serverIP, serverPort)) {
    Serial.print(".");
    delay(1000);
  }
  Serial.println(" connected to Raspberry Pi!");
}

void loop() {
  // compute dt
  unsigned long now = micros();
  double dt = (now - lastMicros) * 1e-6;
  if (dt <= 0) return;
  lastMicros = now;

  // read imu
  int16_t ax, ay, az, gx, gy, gz;
  mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);

  // convert gyro -> deg/s
  double gyroZ_dps = (gz - gyroZ_offset) / GYRO_SENS_250;

  // low-pass filter
  gyro_lpf = (1.0 - LPF_BETA) * gyro_lpf + LPF_BETA * gyroZ_dps;

  // integrate yaw
  yaw_est += gyro_lpf * dt;

  // wrap yaw to [-180, 180]
  double yaw_wrapped = fmod(yaw_est + 540.0, 360.0) - 180.0;

  // send to Raspberry Pi every 100 ms
  static unsigned long lastSend = 0;
  if (millis() - lastSend > 100) {
    lastSend = millis();
    if (client.connected()) {
      client.print(String(yaw_wrapped, 3) + "\n"); // send yaw in degrees
    } else {
      if (client.connect(serverIP, serverPort)) {
        Serial.println("Reconnected to Raspberry Pi");
      }
    }
  }

  // debug print every 500 ms
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 500) {
    lastPrint = millis();
    Serial.print("Yaw: ");
    Serial.println(yaw_wrapped, 3);
  }
}
