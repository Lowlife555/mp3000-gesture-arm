/**
 * uart2.h — USART2 (PA2/PA3) 接 ST-LINK 虚拟串口 → 树莓派 /dev/ttyACM0
 */
#ifndef UART2_H
#define UART2_H

#include <stdint.h>

void uart2_init(uint32_t baud);

void uart2_putc(char c);
void uart2_puts(const char *s);
void uart2_flush(void);

/* 取一行（不含 \r\n）。返回 1 表示拿到完整一行，0 表示还没凑齐。
 * 非阻塞，可以在主循环里每轮调用。 */
int uart2_getline(char *out, uint16_t maxlen);

/* 用于诊断：接收溢出计数 */
uint32_t uart2_overrun(void);

#endif /* UART2_H */
