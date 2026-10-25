/**
 * keys.c — 按键扫描与消抖
 *
 * 为什么不用 EXTI 中断：
 *   消抖本来就要"等 20 ms 再看一眼"，用中断再加定时器反而更啰嗦。
 *   四个键 10 ms 轮询一次的成本可以忽略，而且状态一眼可见、好调试。
 *
 * PC13 说明：Nucleo 板上 B1 键已经有外部上拉，这里再开内部上拉没有坏处
 *   （两个上拉并联只会让上升沿更快）。如果哪天发现 PC13 一直读 0，
 *   说明板上是下拉接法，把 KEY_BACK_PULL 改成 GPIO_PULL_NONE 再试。
 */

#include "keys.h"
#include "board_pins.h"
#include "delay.h"

#define KEY_BACK_PULL   GPIO_PULL_UP

static uint8_t  s_raw[KEY_COUNT];        /* 最近一次读到的电平 */
static uint8_t  s_state[KEY_COUNT];      /* 消抖后的稳定状态，1=按住 */
static uint32_t s_change_ms[KEY_COUNT];  /* 电平最后一次变化的时刻 */
static uint32_t s_press_ms[KEY_COUNT];   /* 本次按下的起始时刻 */
static uint8_t  s_pressed;               /* 待取走的新按下事件 */
static uint8_t  s_released;              /* 待取走的新松开事件 */

static void one_init(GPIO_TypeDef *port, uint8_t pin, uint8_t pull)
{
    gpio_mode(port, pin, GPIO_MODE_IN);
    gpio_pull(port, pin, pull);
}

void keys_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOCEN;
    (void)RCC->AHB2ENR;

    one_init(KEY_UP_PORT,   KEY_UP_PIN,   GPIO_PULL_UP);
    one_init(KEY_DOWN_PORT, KEY_DOWN_PIN, GPIO_PULL_UP);
    one_init(KEY_OK_PORT,   KEY_OK_PIN,   GPIO_PULL_UP);
    one_init(KEY_BACK_PORT, KEY_BACK_PIN, KEY_BACK_PULL);

    /* 上电先采一次，避免第一次扫描就产生假事件 */
    {
        uint8_t v = 0;
        if (!PIN_READ(KEY_UP_PORT,   KEY_UP_PIN))   v |= KEY_BIT(KEY_UP);
        if (!PIN_READ(KEY_DOWN_PORT, KEY_DOWN_PIN)) v |= KEY_BIT(KEY_DOWN);
        if (!PIN_READ(KEY_OK_PORT,   KEY_OK_PIN))   v |= KEY_BIT(KEY_OK);
        if (!PIN_READ(KEY_BACK_PORT, KEY_BACK_PIN)) v |= KEY_BIT(KEY_BACK);

        uint8_t i;
        uint32_t now = millis();
        for (i = 0; i < KEY_COUNT; i++) {
            s_raw[i] = s_state[i] = (v & KEY_BIT(i)) ? 1U : 0U;
            s_change_ms[i] = now;
            s_press_ms[i] = 0;
        }
    }
    s_pressed = 0;
    s_released = 0;
}

void keys_scan(void)
{
    uint8_t v = 0;
    uint8_t i;
    uint32_t now = millis();

    if (!PIN_READ(KEY_UP_PORT,   KEY_UP_PIN))   v |= KEY_BIT(KEY_UP);
    if (!PIN_READ(KEY_DOWN_PORT, KEY_DOWN_PIN)) v |= KEY_BIT(KEY_DOWN);
    if (!PIN_READ(KEY_OK_PORT,   KEY_OK_PIN))   v |= KEY_BIT(KEY_OK);
    if (!PIN_READ(KEY_BACK_PORT, KEY_BACK_PIN)) v |= KEY_BIT(KEY_BACK);

    for (i = 0; i < KEY_COUNT; i++) {
        uint8_t raw = (v & KEY_BIT(i)) ? 1U : 0U;

        if (raw != s_raw[i]) {
            s_raw[i] = raw;
            s_change_ms[i] = now;      /* 电平刚变，重新计时 */
            continue;
        }
        /* 电平已经稳定 DEBOUNCE_MS 以上，才承认它 */
        if (raw != s_state[i] && (uint32_t)(now - s_change_ms[i]) >= DEBOUNCE_MS) {
            s_state[i] = raw;
            if (raw) {
                s_pressed |= KEY_BIT(i);
                s_press_ms[i] = now;
            } else {
                s_released |= KEY_BIT(i);
                s_press_ms[i] = 0;
            }
        }
    }
}

uint8_t keys_down(void)
{
    uint8_t m = 0, i;
    for (i = 0; i < KEY_COUNT; i++) {
        if (s_state[i]) m |= KEY_BIT(i);
    }
    return m;
}

uint8_t keys_take_pressed(void)
{
    uint8_t m = s_pressed;
    s_pressed = 0;
    return m;
}

uint8_t keys_take_released(void)
{
    uint8_t m = s_released;
    s_released = 0;
    return m;
}

uint32_t keys_held_ms(key_id_t k)
{
    if (k >= KEY_COUNT || !s_state[k]) {
        return 0;
    }
    return (uint32_t)(millis() - s_press_ms[k]);
}
