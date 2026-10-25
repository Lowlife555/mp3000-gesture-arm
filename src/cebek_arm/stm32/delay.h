/**
 * delay.h — 基于 SysTick 的毫秒时基
 */
#ifndef DELAY_H
#define DELAY_H

#include <stdint.h>

/* 启动 1 kHz SysTick 中断。必须在 clock_init() 之后调用，
 * 因为它的重装值取决于当前 SYSCLK。 */
void delay_init(void);

/* 自开机以来的毫秒数（32 位，约 49.7 天回绕） */
uint32_t millis(void);

void delay_ms(uint32_t ms);
void delay_us(uint32_t us);

/* 超时判断辅助：返回 1 表示从 t0 起已经过了 ms 毫秒（处理回绕） */
uint8_t elapsed(uint32_t t0, uint32_t ms);

#endif /* DELAY_H */
