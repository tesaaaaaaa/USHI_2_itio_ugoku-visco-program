// 必要なライブラリをインクルード
#include <Arduino.h>
#include <stdio.h>

TaskHandle_t thp[2];               //マルチスレッドのタスクハンドル格納用
QueueHandle_t xQueue_MotorSpeed;   //Queueを使う準備 [キューハンドル名]
QueueHandle_t xQueue_SensorValue;  //Queueを使う準備 [キューハンドル名]

// モーターのピン設定
const int motorPin1 = 14;
const int motorPin2 = 32;
const int motorPin3 = 27;
const int motorPin4 = 33;

// マイクロステッピングのステップシーケンスの定義
const int stepsPerRevolution = 200;  // ステッピングモーターの1回転あたりのステップ数
int stepNumber = 0;                  // 現在のステップ番号
// int microsteps[] = { 0b0001, 0b0000 };  // ハーフステッピングのステップシーケンス
int microsteps[] = { 0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001 };  // ハーフステッピングのステップシーケンス
// int microsteps[] = { 0b0011, 0b0110, 0b1100, 0b1001 };  // ハーフステッピングのステップシーケンス

// ロードセル用ライブラリの読み込み
// https://github.com/RobTillaart/HX711
// version : 0.4.0
#include "HX711.h"
HX711 scale;
//ロードセルのピン設定
uint8_t dataPin = 19;
uint8_t clockPin = 18;

// モーターピンを出力モードに設定する関数
void MotorPinSetup() {
  // モーターピンを出力モードに設定
  pinMode(motorPin1, OUTPUT);
  pinMode(motorPin2, OUTPUT);
  pinMode(motorPin3, OUTPUT);
  pinMode(motorPin4, OUTPUT);
}

// ステッピングモーターを1ステップ動かす関数
void NextStep() {
  // マイクロステッピングのステップシーケンスに基づいてモーターを動かす
  digitalWrite(motorPin1, bitRead(microsteps[stepNumber], 0));
  digitalWrite(motorPin2, bitRead(microsteps[stepNumber], 1));
  digitalWrite(motorPin3, bitRead(microsteps[stepNumber], 2));
  digitalWrite(motorPin4, bitRead(microsteps[stepNumber], 3));

  // 次のステップ番号に進む
  stepNumber++;
  if (stepNumber == 8) {
    stepNumber = 0;  // ステップ番号をリセット
  }
}


void Motor_core0(void *args) {
  // ステップ間の秒数の測定用
  unsigned long current_time = 0;
  unsigned long last_change_time = 0;
  // モーターの速度
  unsigned int inputValue = 0;
  unsigned int motor_delay = 0;

  while (true) {
    current_time = micros();
    // シリアルモニターからの入力をチェック
    if (xQueueReceive(xQueue_MotorSpeed, &inputValue, 0)) {
      // 速度の設定
      motor_delay = inputValue;
    }

    // 速度が0の場合、モーターに電圧をかけない
    if (motor_delay == 0) {
      digitalWrite(motorPin1, LOW);
      digitalWrite(motorPin2, LOW);
      digitalWrite(motorPin3, LOW);
      digitalWrite(motorPin4, LOW);
    } else if ((current_time - last_change_time) > motor_delay) {
      // モーターを1ステップ動かす
      NextStep();
      last_change_time = micros();
    }
  }
}

//ロードセルのピンを設定
void SetupLoadcell() {
  scale.begin(dataPin, clockPin);
}


void setup() {
  // シリアル通信を開始
  Serial.begin(115200);
  // シリアル通信のタイムアウト設定
  Serial.setTimeout(50);

  pinMode(25, OUTPUT);
  pinMode(26, OUTPUT);
  digitalWrite(25, HIGH);
  digitalWrite(26, HIGH);

  // モーターピンを出力モードに設定
  MotorPinSetup();
  //core0のWDTを無効化する（delayなしで高速の無限ループが可能になる。モーター用）
  disableCore0WDT();

  //ロードセルのピンを設定し、ロードセル用のライブラリのバージョンを表示
  SetupLoadcell();

  xQueue_MotorSpeed = xQueueCreate(4, sizeof(int));       //モーターの速度変更用（ユーザー→モーター）
  xQueue_SensorValue = xQueueCreate(4, sizeof(int32_t));  //センサーの値通知用（センサー→ユーザー）
  //xQueueCreate( [待ち行列の席数], [一席あたりのバイト数] );

  //スレッドの準備
  xTaskCreatePinnedToCore(Motor_core0, "Motor_core0", 4096, NULL, 2, &thp[0], 0);    //モーターを回転させる関数をcore0でスレッドとして開始
  xTaskCreatePinnedToCore(output_core1, "output_core1", 4096, NULL, 1, &thp[1], 1);  //センサーの値を収集する関数をcore1でスレッドとして開始
}


bool is_output_running = false;
unsigned int motor_delay = 0;  //モータースピード記録用の変数

void output_core1(void *args) {
  int32_t rawData = 0;  //送信データの変数
  while (1) {
    if (is_output_running) {
      rawData = scale.read();
      char output[64];
      sprintf(output, "[data], %lu, %d, %d", millis(), rawData, motor_delay);
      Serial.println(output);
    }
    delay(10);
  }
}

void loop() {
  // シリアルモニターからの入力をチェック
  if (Serial.available() > 0) {
    String received = Serial.readStringUntil('\n');
    String command = received.substring(0, received.indexOf(' '));
    String argument_str = received.substring(received.indexOf(' ') + 1);
    float argument = argument_str.toFloat();

    if (command == "set_speed") {
      //値域のチェック
      if (argument < 0) {
        motor_delay = 0;
      } else {
        motor_delay = static_cast<unsigned int>(argument);
      }
      Serial.print("speed was set : ");
      Serial.println(motor_delay);
      xQueueSend(xQueue_MotorSpeed, &motor_delay, 0);

    } else if (command == "start_output") {
      is_output_running = true;
      Serial.println("output started!");

    } else if (command == "stop_output") {
      is_output_running = false;
      Serial.println("output stopped.");

    } else {
      Serial.println("Unknown command.");
    }
  }
  // 消費電力を抑える＆ほかのタスクのリソースを食いつぶさないように（無くても動く）
  delay(1);
}