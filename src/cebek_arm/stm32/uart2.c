/**
 * uart2.c — USART2 收发（中断接收 + 环形缓冲）
 *
 * 波特率 115200 8N1。ST-LINK 的虚拟串口在 Nucleo-64 上接的就是 PA2/PA3，
 * 所以插一根 USB 线到树莓派，系统里会出现 /dev/ttyACM0，不需要额外飞线。
 */

#include "uart2.h"
#include "board_pins.h"
#include "clock.h"

#define RX_RING     256U

static volatile uint8_t  s_rx[RX_RING];
static volatile uint16_t s_head;          /* 中断写 */
static volatile uint16_t s_tail;          /* 主循环读 */
static volatile uint32_t s_overrun;

/* 行拼装缓冲 */
static char     s_line[96];
static uint16_t s_line_len;

/* USART2 的寄存器位直接用 CMSIS 头里的宏（cmsis/ 已随工程固定）。
 * RM0351 §38：CR1[0]=UE [2]=RE [3]=TE [5]=RXNEIE；
 *             ISR[5]=RXNE [3]=ORE [7]=TXE；ICR[3]=ORECF */

void uart2_init(uint32_t baud)
{
    RCC->AHB2ENR  |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
    (void)RCC->APB1ENR1;

    /* PA2 = TX, PA3 = RX, AF7 */
    gpio_mode(UART_GPIO, UART_TX_PIN, GPIO_MODE_AF);
    gpio_mode(UART_GPIO, UART_RX_PIN, GPIO_MODE_AF);
    gpio_af(UART_GPIO, UART_TX_PIN, UART_AF);
    gpio_af(UART_GPIO, UART_RX_PIN, UART_AF);
    gpio_speed(UART_GPIO, UART_TX_PIN, GPIO_SPEED_HIGH);
    gpio_speed(UART_GPIO, UART_RX_PIN, GPIO_SPEED_HIGH);
    gpio_pushpull(UART_GPIO, UART_TX_PIN);
    gpio_pull(UART_GPIO, UART_TX_PIN, GPIO_PULL_UP);
    gpio_pull(UART_GPIO, UART_RX_PIN, GPIO_PULL_UP);

    USART2->CR1 = 0;
    /* OVER8 = 0，BRR = fCK / baud，四舍五入到最近的整数分频 */
    USART2->BRR = (uint16_t)((clock_sysclk() + (baud / 2U)) / baud);
    USART2->CR2 = 0;
    USART2->CR3 = 0;
    USART2->CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE;

    NVIC_SetPriority(USART2_IRQn, 2);
    NVIC_EnableIRQ(USART2_IRQn);

    s_head = s_tail = 0;
    s_overrun = 0;
    s_line_len = 0;
}

void USART2_IRQHandler(void)
{
    uint32_t isr = USART2->ISR;

    if (isr & USART_ISR_RXNE) {
        uint8_t b = (uint8_t)(USART2->RDR & 0xFFU);
        uint16_t next = (uint16_t)((s_head + 1U) % RX_RING);
        if (next == s_tail) {
            s_overrun++;                   /* 满了就丢，不阻塞中断 */
        } else {
            s_rx[s_head] = b;
            s_head = next;
        }
    }
    if (isr & USART_ISR_ORE) {
        USART2->ICR = USART_ICR_ORECF;     /* 不清会一直进中断 */
        s_overrun++;
    }
}

void uart2_putc(char c)
{
    while (!(USART2->ISR & USART_ISR_TXE)) {
        ;
    }
    USART2->TDR = (uint8_t)c;
}

void uart2_puts(const char *s)
{
    while (*s) {
        uart2_putc(*s++);
    }
}

void uart2_flush(void)
{
    while (!(USART2->ISR & USART_ISR_TXE)) {
        ;
    }
}

int uart2_getline(char *out, uint16_t maxlen)
{
    while (s_tail != s_head) {
        char c = (char)s_rx[s_tail];
        s_tail = (uint16_t)((s_tail + 1U) % RX_RING);

        if (c == '\r') {
            continue;
        }
        if (c == '\n') {
            uint16_t n = s_line_len;
            if (n >= maxlen) n = (uint16_t)(maxlen - 1U);
            {
                uint16_t i;
                for (i = 0; i < n; i++) out[i] = s_line[i];
                out[n] = '\0';
            }
            s_line_len = 0;
            return 1;
        }
        if (s_line_len < sizeof(s_line) - 1U) {
            s_line[s_line_len++] = c;
        } else {
            s_line_len = 0;                /* 超长行丢弃，重新同步 */
        }
    }
    return 0;
}

uint32_t uart2_overrun(void)
{
    return s_overrun;
}
