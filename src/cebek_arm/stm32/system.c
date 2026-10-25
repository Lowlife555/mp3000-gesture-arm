/**
 * system.c — 最小启动支撑（不依赖 HAL）
 *
 * startup_stm32l476xx.s 在跳进 __main 之前会调用 SystemInit()，
 * 所以这个函数必须存在。这里只做两件事：
 *   1. 打开 FPU（L476 有单精度 FPU，不开的话浮点指令会进 UsageFault）
 *   2. 提供 SystemCoreClock 变量（有些库函数会引用它）
 *
 * 真正的时钟树在 clock.c 的 clock_init() 里手工配置，
 * 这里保持"复位默认状态不动"，让 SystemInit 的行为可预测。
 */

#include "stm32l4xx.h"

/* 该值在 clock_init() 成功后由 clock.c 更新 */
uint32_t SystemCoreClock = 4000000U;   /* 复位后是 MSI 4 MHz */

void SystemInit(void)
{
    /* CPACR: 允许 CP10 / CP11 全访问 = 使能 FPU */
    SCB->CPACR |= (0xFu << 20);
    __DSB();
    __ISB();
}

void SystemCoreClockUpdate(void)
{
    SystemCoreClock = 80000000U;
}
