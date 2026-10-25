/**
 * clock.h — 80 MHz 系统时钟
 */
#ifndef CLOCK_H
#define CLOCK_H

#include <stdint.h>

/* 把系统时钟从复位默认的 MSI 4 MHz 拉到 HSI16 + PLL = 80 MHz
 * 返回 0 成功，非 0 表示 PLL 没锁定（此时芯片仍在 MSI 上跑，可安全处理） */
int clock_init(void);

/* 当前 SYSCLK（Hz） */
uint32_t clock_sysclk(void);

#endif /* CLOCK_H */
