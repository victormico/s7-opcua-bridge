/*
 * S7 -> OPC UA Gateway: microcontroller status display on the UNO Q LED matrix.
 *
 * The Linux (Python) side runs the S7 <-> OPC UA bridge and pushes live health
 * to this sketch once per second over the Router Bridge RPC:
 *
 *     Bridge.call("set_status", plc_ok, opcua_ok, alarm)   // from Python
 *
 * The 13x8 matrix shows a friendly status:
 *     healthy      (plc_ok && opcua_ok, no alarm)  -> smiley face
 *     alarm        (alarm flag set)                -> scrolling "ALARM: TEMP HIGH"
 *     PLC down     (opcua_ok, !plc_ok)             -> scrolling "PLC OFFLINE"
 *     server down  (!opcua_ok)                     -> blank
 *
 * LED_BUILTIN mirrors "OPC UA up" (lit) for a quick glance.
 */

#include <ArduinoGraphics.h>      // must precede Arduino_LED_Matrix.h (enables text/graphics base)
#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>

Arduino_LED_Matrix matrix;

static const int MATRIX_W = 13;
static const int MATRIX_H = 8;

// UNO Q built-in LED polarity (LOW = lit), per the Arduino examples.
#define LED_ON  LOW
#define LED_OFF HIGH

// Latest health pushed from Python (updated on the Bridge thread).
static volatile bool g_plc_ok = false;
static volatile bool g_opcua_ok = false;
static volatile bool g_alarm = false;

// 1 = lit. A round face with two eyes and a smile.
static const uint8_t SMILEY[MATRIX_H][MATRIX_W] = {
  {0,0,0,1,1,1,1,1,1,1,0,0,0},
  {0,0,1,0,0,0,0,0,0,0,1,0,0},
  {0,1,0,1,0,0,0,0,0,1,0,1,0},  // eyes
  {0,1,0,0,0,0,0,0,0,0,0,1,0},
  {0,1,0,1,0,0,0,0,0,1,0,1,0},  // smile corners
  {0,1,0,0,1,0,0,0,1,0,0,1,0},
  {0,0,1,0,0,1,1,1,0,0,1,0,0},  // smile bottom
  {0,0,0,1,1,1,1,1,1,1,0,0,0},
};

// RPC target invoked by the Python side every bridge cycle.
void set_status(bool plc_ok, bool opcua_ok, bool alarm) {
  g_plc_ok = plc_ok;
  g_opcua_ok = opcua_ok;
  g_alarm = alarm;
}

static void drawSmiley() {
  uint8_t buf[MATRIX_H * MATRIX_W];
  for (int y = 0; y < MATRIX_H; y++) {
    for (int x = 0; x < MATRIX_W; x++) {
      buf[y * MATRIX_W + x] = SMILEY[y][x];
    }
  }
  matrix.draw(buf);
}

// Scroll a message once across the matrix (blocks for the scroll duration;
// set_status keeps updating state on its own thread meanwhile).
static void scrollText(const char *msg) {
  matrix.beginDraw();
  matrix.stroke(255, 255, 255);
  matrix.textFont(Font_5x7);
  matrix.beginText(0, 1, 255, 255, 255);
  matrix.print(msg);
  matrix.endText(SCROLL_LEFT);
  matrix.endDraw();
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LED_OFF);

  matrix.begin();
  matrix.textScrollSpeed(60);
  matrix.clear();

  Bridge.begin();
  Bridge.provide("set_status", set_status);
}

void loop() {
  if (g_alarm) {
    digitalWrite(LED_BUILTIN, LED_ON);
    scrollText("  ALARM: TEMP HIGH  ");
  } else if (g_plc_ok && g_opcua_ok) {
    digitalWrite(LED_BUILTIN, LED_ON);
    drawSmiley();      // healthy: steady smiley
    delay(150);
  } else if (g_opcua_ok) {
    digitalWrite(LED_BUILTIN, LED_OFF);
    scrollText("  PLC OFFLINE  ");
  } else {
    digitalWrite(LED_BUILTIN, LED_OFF);
    matrix.clear();    // server not running yet
    delay(150);
  }
}
