/**
 * clock.c — HSI16 + PLL → 80 MHz（纯寄存器，不用 HAL）
 *
 * 为什么用 HSI16 而不是 HSE：
 *   Nucleo 的 HSE 来自 ST-LINK 的 MCO 输出，只有在 ST-LINK 固件那条路
 *   正常工作且板子跳线正确时才有 8 MHz。HSI16 是片内 RC，上电就有，
 *   整个方案不依赖外部器件 → 更可靠，代价是 ±1% 精度。
 *   对"按时间开电机"这件事，1% 完全够了。
 *
 * 时钟树：
 *   HSI16 16 MHz → PLLM(/4) → 4 MHz → PLLN(×40) → 160 MHz → PLLR(/2) → 80 MHz
 *   AHB = 80 MHz, APB1 = 80 MHz, APB2 = 80 MHz（L476 两者上限都是 80 MHz）
 *
 * 关键顺序（错了会跑飞）：
 *   1. 先把 PWR 调到 Range 1（复位默认是 Range 2，最高只到 26 MHz）
 *   2. 调高 Flash 等待周期（80 MHz 需要 4 WS）—— 必须在提频之前
 *   3. 锁 PLL，再切 SYSCLK
 */

#include "clock.h"
#include "stm32l4xx.h"

#define PLLM_DIV        4U
#define PLLN_MUL        40U
#define PLLR_DIV        2U
#define TARGET_HZ       80000000U

static uint32_t s_sysclk = 4000000U;

static int wait_flag(volatile uint32_t *reg, uint32_t mask, uint32_t want, uint32_t spin)
{
    while (spin--) {
        if ((*reg & mask) == (want ? mask : 0U)) {
            return 0;
        }
    }
    return -1;
}

int clock_init(void)
{
    /* ── 1) 电压档 Range 1 ── */
    /* PWR_CR1.VOS[1:0] = 01 为 Range 1；复位值是 10 (Range 2) */
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;
    PWR->CR1 = (PWR->CR1 & ~(3UL << 9)) | (1UL << 9);
    if (wait_flag(&PWR->SR2, PWR_SR2_VOSF, 0U, 1000000U) != 0) {
        return -1;
    }

    /* ── 2) Flash：4 等待周期 + 预取 / 指令缓存 / 数据缓存 ── */
    FLASH->ACR = (FLASH->ACR & ~0x0FUL) | 4UL;      /* LATENCY = 4 WS */
    FLASH->ACR |= FLASH_ACR_PRFTEN | FLASH_ACR_ICEN | FLASH_ACR_DCEN;

    /* ── 3) 打开 HSI16 ── */
    RCC->CR |= RCC_CR_HSION;
    if (wait_flag(&RCC->CR, RCC_CR_HSIRDY, 1U, 1000000U) != 0) {
        return -2;
    }

    /* ── 4) AHB / APB 全不分频（必须在切到 PLL 之前设好）── */
    RCC->CFGR &= ~(RCC_CFGR_HPRE | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2);

    /* ── 5) 配 PLL 参数，但先不开 ── */
    RCC->PLLCFGR =
          (2UL << 0)                        /* PLLSRC = HSI16 */
        | ((uint32_t)(PLLM_DIV - 1U) << 4)   /* PLLM 编码为 分频值-1 */
        | ((uint32_t)PLLN_MUL << 8)          /* PLLN 乘数 */
        | (RCC_PLLCFGR_PLLREN)               /* 使能 R 路输出 */
        | (0UL << 25);                       /* PLLR = 00 → /2 */

    RCC->CR |= RCC_CR_PLLON;
    if (wait_flag(&RCC->CR, RCC_CR_PLLRDY, 1U, 2000000U) != 0) {
        return -3;
    }

    /* ── 6) 切 SYSCLK 到 PLL ── */
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | (3UL << 0);   /* SW = PLL */
    if (wait_flag(&RCC->CFGR, RCC_CFGR_SWS, 1U, 2000000U) != 0) {
        /* SWS == 10 表示已切到 PLL；这里用宽松判断再确认一次 */
    }
    if ((RCC->CFGR & RCC_CFGR_SWS) != (2UL << 2)) {
        return -4;
    }

    s_sysclk = TARGET_HZ;
    SystemCoreClock = TARGET_HZ;
    return 0;
}

uint32_t clock_sysclk(void)
{
    return s_sysclk;
}
