/**
 * board_pins.h — 所有引脚定义集中在这一个文件
 *
 * 引脚分配来自你 Wellspan Health Watch 的 tft-lcd 工程（已验证在实物上跑通过）：
 *   LCD ILI9341 240x320 RGB565，硬件 SPI1
 *     SCK  = PA5   (AF5)
 *     MISO = PA6   (AF5，本驱动不读屏，未配置)
 *     MOSI = PA7   (AF5)
 *     DC   = PA11  (通用输出)
 *     RST  = PA12  (通用输出)
 *     没有 CS，没有背光引脚（板上直接拉死）
 *   四键，低电平有效，内部上拉
 *     UP   = PA0
 *     DOWN = PA4
 *     OK   = PB1
 *     BACK = PC13
 *   USART2 接 ST-LINK 虚拟串口 → 树莓派 /dev/ttyACM0
 *     TX = PA2  (AF7)
 *     RX = PA3  (AF7)
 *
 * ⚠️ 注意：PA11/PA12 同时也是 L476 的 USB_DM/DP。
 *    这块板子拿它们做了 LCD 的 DC/RST，所以 **本板不能再用 L476 的原生 USB**。
 *    机械臂的 USB 由树莓派承担，分工见 README。
 */

#ifndef BOARD_PINS_H
#define BOARD_PINS_H

#include "stm32l4xx.h"

/* ── LCD ─────────────────────────────────────────────── */
#define LCD_GPIO        GPIOA
#define LCD_SCK_PIN     5
#define LCD_MISO_PIN    6      /* 未使用 */
#define LCD_MOSI_PIN    7
#define LCD_DC_PIN      11
#define LCD_RST_PIN     12
#define LCD_AF          (5U)   /* AF5 = SPI1 */

/* ── 按键 ─────────────────────────────────────────────── */
#define KEY_UP_PORT     GPIOA
#define KEY_UP_PIN      0
#define KEY_DOWN_PORT   GPIOA
#define KEY_DOWN_PIN    4
#define KEY_OK_PORT     GPIOB
#define KEY_OK_PIN      1
#define KEY_BACK_PORT   GPIOC
#define KEY_BACK_PIN    13

/* ── 串口（ST-LINK VCP）──────────────────────────────── */
#define UART_GPIO       GPIOA
#define UART_TX_PIN     2
#define UART_RX_PIN     3
#define UART_AF         (7U)   /* AF7 = USART2 */

/* ── 常用小工具 ───────────────────────────────────────── */
#define PIN_SET(port, pin)      ((port)->BSRR = (1UL << (pin)))
#define PIN_CLR(port, pin)      ((port)->BRR  = (1UL << (pin)))
#define PIN_WRITE(port, pin, v) ((v) ? PIN_SET(port, pin) : PIN_CLR(port, pin))
#define PIN_READ(port, pin)     (((port)->IDR >> (pin)) & 1U)

/* GPIO 模式 / 上下拉 / 复用号，写法统一好查 */
#define GPIO_MODE_IN            0U
#define GPIO_MODE_OUT           1U
#define GPIO_MODE_AF            2U
#define GPIO_MODE_ANALOG        3U
#define GPIO_PULL_NONE          0U
#define GPIO_PULL_UP            1U
#define GPIO_PULL_DOWN          2U
#define GPIO_SPEED_LOW          0U
#define GPIO_SPEED_MED          1U
#define GPIO_SPEED_HIGH         2U
#define GPIO_SPEED_VHIGH        3U

static inline void gpio_mode(GPIO_TypeDef *p, uint8_t pin, uint8_t mode)
{
    p->MODER = (p->MODER & ~(3UL << (pin * 2))) | ((uint32_t)mode << (pin * 2));
}

static inline void gpio_pull(GPIO_TypeDef *p, uint8_t pin, uint8_t pull)
{
    p->PUPDR = (p->PUPDR & ~(3UL << (pin * 2))) | ((uint32_t)pull << (pin * 2));
}

static inline void gpio_speed(GPIO_TypeDef *p, uint8_t pin, uint8_t spd)
{
    p->OSPEEDR = (p->OSPEEDR & ~(3UL << (pin * 2))) | ((uint32_t)spd << (pin * 2));
}

static inline void gpio_af(GPIO_TypeDef *p, uint8_t pin, uint8_t af)
{
    if (pin < 8) {
        p->AFR[0] = (p->AFR[0] & ~(0xFUL << (pin * 4))) | ((uint32_t)af << (pin * 4));
    } else {
        p->AFR[1] = (p->AFR[1] & ~(0xFUL << ((pin - 8) * 4)))
                    | ((uint32_t)af << ((pin - 8) * 4));
    }
}

static inline void gpio_pushpull(GPIO_TypeDef *p, uint8_t pin)
{
    p->OTYPER &= ~(1UL << pin);
}

#endif /* BOARD_PINS_H */
