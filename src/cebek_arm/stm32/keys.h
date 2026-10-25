/**
 * keys.h — 四个按键（PA0 / PA4 / PB1 / PC13），低电平有效
 */
#ifndef KEYS_H
#define KEYS_H

#include <stdint.h>

typedef enum {
    KEY_UP = 0,
    KEY_DOWN,
    KEY_OK,
    KEY_BACK,
    KEY_COUNT
} key_id_t;

#define KEY_BIT(k)      ((uint8_t)(1U << (k)))
#define DEBOUNCE_MS     20U

void keys_init(void);

/* 每 10 ms 调一次（main 循环里靠 millis 判断） */
void keys_scan(void);

/* 当前按住哪些键（位掩码） */
uint8_t keys_down(void);

/* 取走"本次新按下"的事件（读后清零） */
uint8_t keys_take_pressed(void);

/* 取走"本次刚松开"的事件（读后清零） */
uint8_t keys_take_released(void);

/* 当前这一按已经持续多少毫秒（没按住时返回 0） */
uint32_t keys_held_ms(key_id_t k);

#endif /* KEYS_H */
