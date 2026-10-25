/**
 * main.c — Cebek C-9895.2 机械臂 STM32 控制台
 *
 * 分工：
 *   STM32 负责"手和眼"——按键、彩屏、状态机、安全计时，全部在本地实时完成。
 *   树莓派负责"嘴和耳"——它才是 USB 主机，把 3 个字节送进原厂接口板。
 * 两者之间用一根 ST-LINK 虚拟串口，ASCII 行协议（见 arm.c 顶部注释）。
 *
 * 为什么不让 STM32 直接当 USB 主机：
 *   USB Low Speed 位宽 666.7 ns，80 MHz 下每 bit 只有 53 个周期，
 *   而要求边沿抖动在 ±10 ns 内；再加上 NRZI、位填充、CRC5/CRC16、
 *   SETUP/DATA/ACK 三段握手、每 1 ms 的 SOF —— GPIO 翻转做不到。
 *   走硬件主机又要占掉 PA11/PA12（本板给了 LCD 的 DC/RST）并自写主机栈。
 *   所以 V1 用树莓派当 USB 桥，V2 可以用 MAX3421E 让 STM32 独立。
 */

#include "stm32l4xx.h"
#include "clock.h"
#include "delay.h"
#include "lcd.h"
#include "keys.h"
#include "arm.h"
#include "ui.h"

int main(void)
{
    uint32_t t_key = 0;
    uint32_t t_ping = 0;
    uint32_t now;

    /* 时钟：MSI 4 MHz → PLL 80 MHz */
    (void)clock_init();

    /* 1 kHz 时基 + DWT 微秒计数 */
    delay_init();

    keys_init();

    lcd_init();          /* 内含 120 ms 硬复位等待 */

    arm_init();          /* 上电先发 00 00 00，防止臂在跑 */
    ui_init();

    t_key = millis();
    t_ping = t_key;

    for (;;) {
        now = millis();

        /* 串口回话（OK/PONG/ERR/TMO）每轮都收 */
        arm_poll();

        /* 按键每 10 ms 扫一次 */
        if ((uint32_t)(now - t_key) >= 10U) {
            t_key = now;
            keys_scan();
        }

        /* 心跳 500 ms 一次；链路判定窗口是 1500 ms */
        if ((uint32_t)(now - t_ping) >= 500U) {
            t_ping = now;
            arm_ping();
        }

        ui_task();
    }
}
