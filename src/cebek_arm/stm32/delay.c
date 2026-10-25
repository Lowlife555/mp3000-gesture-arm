/**
 * delay.c — SysTick 1 kHz 时基 + DWT 微秒延时
 *
 * 为什么不用循环空转凑延时：
 *   编译器优化等级一改，空转的次数就变了，延时跟着漂。
 *   而"按时间开电机"这件事全靠时间准，所以时基必须是硬件计数。
 */

#include "delay.h"
#include "stm32l4xx.h"
#include "clock.h"

static volatile uint32_t s_ms;

void SysTick_Handler(void)
{
    s_ms++;
}

void delay_init(void)
{
    /* DWT 周期计数器（微秒延时用） */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    /* SysTick 每 1 ms 中断一次 */
    SysTick->LOAD = (clock_sysclk() / 1000U) - 1U;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk    /* 用处理器时钟 */
                 | SysTick_CTRL_TICKINT_Msk       /* 开中断 */
                 | SysTick_CTRL_ENABLE_Msk;
}

uint32_t millis(void)
{
    return s_ms;
}

void delay_ms(uint32_t ms)
{
    uint32_t t0 = s_ms;
    while ((s_ms - t0) < ms) {
        __NOP();
    }
}

void delay_us(uint32_t us)
{
    uint32_t start = DWT->CYCCNT;
    uint32_t ticks = us * (clock_sysclk() / 1000000U);
    while ((DWT->CYCCNT - start) < ticks) {
        __NOP();
    }
}

uint8_t elapsed(uint32_t t0, uint32_t ms)
{
    return ((uint32_t)(s_ms - t0) >= ms) ? 1U : 0U;
}
