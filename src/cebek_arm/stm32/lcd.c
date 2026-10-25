/**
 * lcd.c — ILI9341 驱动（寄存器级，无 HAL）
 *
 * 寄存器位直接用移位常量写死，不依赖 CMSIS 里那些宏的名字 ——
 * 换一版 DFP 头文件时宏名可能变，移位不会变。
 */

#include "lcd.h"
#include "board_pins.h"
#include "delay.h"
#include "font_data.h"

/* SPI1 寄存器位直接用 CMSIS 头里的宏 —— cmsis/ 目录已随工程固定住，
 * 版本不会再变，所以不需要自己再写一遍（写了反而会撞重定义警告）。
 * 只有下面这一个 CMSIS 里没有，补上：DS[3:0]=0111 表示 8 位数据帧。 */
#define SPI_CR2_DS_8BIT (7UL << 8)

/* ILI9341 命令 */
#define CMD_SWRESET     0x01
#define CMD_SLPOUT      0x11
#define CMD_GAMMASET    0x26
#define CMD_DISPON      0x29
#define CMD_CASET       0x2A
#define CMD_PASET       0x2B
#define CMD_RAMWR       0x2C
#define CMD_MADCTL      0x36
#define CMD_PIXFMT      0x3A

/* 竖屏 240x320，180°（和你 Wellspan 工程一致：MX|MY|BGR） */
#define MADCTL_180      (0xC8)          /* MY=0x80 MX=0x40 BGR=0x08 */

static uint8_t s_glyph[FONT_W * FONT_H * 2];

/* ── 底层 ─────────────────────────────────────────────── */

static inline void dc_low(void)  { PIN_CLR(GPIOA, LCD_DC_PIN); }
static inline void dc_high(void) { PIN_SET(GPIOA, LCD_DC_PIN); }

static inline void spi_tx(uint8_t b)
{
    while (!(SPI1->SR & SPI_SR_TXE)) {
        ;
    }
    *(volatile uint8_t *)&SPI1->DR = b;      /* 8 位帧，写字节寄存器 */
}

static inline void spi_flush(void)
{
    while (SPI1->SR & SPI_SR_BSY) {
        ;
    }
}

static void lcd_wr_reg(uint8_t c)
{
    spi_flush();
    dc_low();
    spi_tx(c);
    spi_flush();
}

static void lcd_wr_data8(uint8_t d)
{
    dc_high();
    spi_tx(d);
}

static void lcd_set_window(uint16_t sx, uint16_t sy, uint16_t w, uint16_t h)
{
    uint16_t ex = (uint16_t)(sx + w - 1);
    uint16_t ey = (uint16_t)(sy + h - 1);

    lcd_wr_reg(CMD_CASET);
    lcd_wr_data8((uint8_t)(sx >> 8));
    lcd_wr_data8((uint8_t)(sx & 0xFF));
    lcd_wr_data8((uint8_t)(ex >> 8));
    lcd_wr_data8((uint8_t)(ex & 0xFF));

    lcd_wr_reg(CMD_PASET);
    lcd_wr_data8((uint8_t)(sy >> 8));
    lcd_wr_data8((uint8_t)(sy & 0xFF));
    lcd_wr_data8((uint8_t)(ey >> 8));
    lcd_wr_data8((uint8_t)(ey & 0xFF));

    lcd_wr_reg(CMD_RAMWR);
}

/* ── 初始化 ───────────────────────────────────────────── */

static void spi1_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;
    (void)RCC->APB2ENR;                      /* 读回确保时钟稳定 */

    /* PA5=SCK, PA7=MOSI → AF5 推挽，最高速 */
    gpio_mode(GPIOA, LCD_SCK_PIN,  GPIO_MODE_AF);
    gpio_mode(GPIOA, LCD_MOSI_PIN, GPIO_MODE_AF);
    gpio_af(GPIOA, LCD_SCK_PIN,  LCD_AF);
    gpio_af(GPIOA, LCD_MOSI_PIN, LCD_AF);
    gpio_speed(GPIOA, LCD_SCK_PIN,  GPIO_SPEED_VHIGH);
    gpio_speed(GPIOA, LCD_MOSI_PIN, GPIO_SPEED_VHIGH);
    gpio_pushpull(GPIOA, LCD_SCK_PIN);
    gpio_pushpull(GPIOA, LCD_MOSI_PIN);
    gpio_pull(GPIOA, LCD_SCK_PIN,  GPIO_PULL_NONE);
    gpio_pull(GPIOA, LCD_MOSI_PIN, GPIO_PULL_NONE);

    /* DC / RST 通用推挽输出 */
    gpio_mode(GPIOA, LCD_DC_PIN,  GPIO_MODE_OUT);
    gpio_mode(GPIOA, LCD_RST_PIN, GPIO_MODE_OUT);
    gpio_speed(GPIOA, LCD_DC_PIN,  GPIO_SPEED_HIGH);
    gpio_speed(GPIOA, LCD_RST_PIN, GPIO_SPEED_LOW);
    gpio_pushpull(GPIOA, LCD_DC_PIN);
    gpio_pushpull(GPIOA, LCD_RST_PIN);
    PIN_SET(GPIOA, LCD_DC_PIN);
    PIN_SET(GPIOA, LCD_RST_PIN);

    /* SPI1：主机、软件 NSS（SSM+SSI 内部拉高）、模式 0、8 位、
     * 波特率分频 /8 → APB2 80 MHz / 8 = 10 MHz */
    SPI1->CR1 = 0;
    SPI1->CR1 = SPI_CR1_MSTR | SPI_CR1_SSM | SPI_CR1_SSI | (2UL << 3);
    SPI1->CR2 = SPI_CR2_FRXTH | SPI_CR2_DS_8BIT;
    SPI1->CR1 |= SPI_CR1_SPE;
}

void lcd_init(void)
{
    spi1_init();

    /* 硬复位：拉低 10 ms 再放高，等 120 ms */
    PIN_CLR(GPIOA, LCD_RST_PIN);
    delay_ms(10);
    PIN_SET(GPIOA, LCD_RST_PIN);
    delay_ms(120);

    /* 下面这段寄存器序列是从你 Wellspan 工程里逐条搬过来的，
     * 不是照抄别处的通用表 —— 这块屏已经用它点亮过，不要随手改。 */
    lcd_wr_reg(0xCF); lcd_wr_data8(0x00); lcd_wr_data8(0xC1); lcd_wr_data8(0x30);
    lcd_wr_reg(0xED); lcd_wr_data8(0x64); lcd_wr_data8(0x03);
                      lcd_wr_data8(0x12); lcd_wr_data8(0x81);
    lcd_wr_reg(0xE8); lcd_wr_data8(0x85); lcd_wr_data8(0x01); lcd_wr_data8(0x7A);
    lcd_wr_reg(0xCB); lcd_wr_data8(0x39); lcd_wr_data8(0x2C); lcd_wr_data8(0x00);
                      lcd_wr_data8(0x34); lcd_wr_data8(0x02);
    lcd_wr_reg(0xF7); lcd_wr_data8(0x20);
    lcd_wr_reg(0xEA); lcd_wr_data8(0x00); lcd_wr_data8(0x00);

    lcd_wr_reg(0xC0); lcd_wr_data8(0x21);          /* Power control */
    lcd_wr_reg(0xC1); lcd_wr_data8(0x11);
    lcd_wr_reg(0xC5); lcd_wr_data8(0x31); lcd_wr_data8(0x3C);
    lcd_wr_reg(0xC7); lcd_wr_data8(0x9F);

    lcd_wr_reg(CMD_MADCTL); lcd_wr_data8(MADCTL_180);
    lcd_wr_reg(CMD_PIXFMT); lcd_wr_data8(0x55);    /* 16 位 RGB565 */

    lcd_wr_reg(0xB1); lcd_wr_data8(0x00); lcd_wr_data8(0x1B);
    lcd_wr_reg(0xB6); lcd_wr_data8(0x0A); lcd_wr_data8(0xA2);

    lcd_wr_reg(0xF2); lcd_wr_data8(0x00);
    lcd_wr_reg(CMD_GAMMASET); lcd_wr_data8(0x01);

    lcd_wr_reg(0xE0);
    lcd_wr_data8(0x0F); lcd_wr_data8(0x20); lcd_wr_data8(0x1D);
    lcd_wr_data8(0x0B); lcd_wr_data8(0x10); lcd_wr_data8(0x0A);
    lcd_wr_data8(0x49); lcd_wr_data8(0xA9); lcd_wr_data8(0x3B);
    lcd_wr_data8(0x0A); lcd_wr_data8(0x15); lcd_wr_data8(0x06);
    lcd_wr_data8(0x0C); lcd_wr_data8(0x06); lcd_wr_data8(0x00);

    lcd_wr_reg(0xE1);
    lcd_wr_data8(0x00); lcd_wr_data8(0x1F); lcd_wr_data8(0x22);
    lcd_wr_data8(0x04); lcd_wr_data8(0x0F); lcd_wr_data8(0x05);
    lcd_wr_data8(0x36); lcd_wr_data8(0x46); lcd_wr_data8(0x46);
    lcd_wr_data8(0x05); lcd_wr_data8(0x0B); lcd_wr_data8(0x09);
    lcd_wr_data8(0x33); lcd_wr_data8(0x39); lcd_wr_data8(0x0F);

    lcd_wr_reg(CMD_SLPOUT);
    delay_ms(120);
    lcd_wr_reg(CMD_DISPON);
    delay_ms(20);

    lcd_clear(COLOR_BG);
}

void lcd_set_backlight(int on)
{
    (void)on;    /* 这块板没有背光控制脚 */
}

/* ── 绘图 ─────────────────────────────────────────────── */

void lcd_fill_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color)
{
    uint32_t n;
    if (w == 0 || h == 0) return;
    if (x >= LCD_W || y >= LCD_H) return;
    if ((uint32_t)x + w > LCD_W) w = (uint16_t)(LCD_W - x);
    if ((uint32_t)y + h > LCD_H) h = (uint16_t)(LCD_H - y);

    lcd_set_window(x, y, w, h);
    lcd_wr_reg(CMD_RAMWR);
    dc_high();
    n = (uint32_t)w * h;
    {
        uint8_t hi = (uint8_t)(color >> 8);
        uint8_t lo = (uint8_t)(color & 0xFF);
        while (n--) {
            spi_tx(hi);
            spi_tx(lo);
        }
    }
    spi_flush();
}

void lcd_clear(uint16_t color)
{
    lcd_fill_rect(0, 0, LCD_W, LCD_H, color);
}

void lcd_hline(uint16_t x, uint16_t y, uint16_t w, uint16_t color)
{
    lcd_fill_rect(x, y, w, 1, color);
}

void lcd_vline(uint16_t x, uint16_t y, uint16_t h, uint16_t color)
{
    lcd_fill_rect(x, y, 1, h, color);
}

void lcd_frame(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color)
{
    lcd_hline(x, y, w, color);
    lcd_hline(x, (uint16_t)(y + h - 1), w, color);
    lcd_vline(x, y, h, color);
    lcd_vline((uint16_t)(x + w - 1), y, h, color);
}

/*
 * 字模格式（来自 font_data.h 的 asc2_1608[95][16]）：
 *   列主序：t 是字节序号，col = t/2，row = (t%2)*8 + 位序
 *   每个字节 8 位对应 8 个连续的行，MSB 是最上面那一行
 *   字符实际尺寸 8 宽 x 16 高，共 16 字节
 * 这里先把整字排成"行主序"的 RGB565 缓冲，再一次性灌进 GRAM，
 * 比逐点亮像素少几十倍的 SPI 事务开销。
 */
void lcd_char(uint16_t x, uint16_t y, char ch, uint16_t fg, uint16_t bg)
{
    uint8_t idx, t, bit;
    uint16_t i;

    if (x + FONT_W > LCD_W || y + FONT_H > LCD_H) return;
    if (ch < ' ' || ch > '~') ch = '?';
    idx = (uint8_t)(ch - ' ');

    for (t = 0; t < 16; t++) {
        uint8_t bits = asc2_1608[idx][t];
        uint16_t col = (uint16_t)(t >> 1);
        for (bit = 0; bit < 8; bit++) {
            uint16_t row = (uint16_t)(((t & 1U) * 8U) + bit);
            uint16_t color = (bits & 0x80) ? fg : bg;
            uint16_t p = (uint16_t)((row * FONT_W + col) * 2);
            s_glyph[p]     = (uint8_t)(color >> 8);
            s_glyph[p + 1] = (uint8_t)(color & 0xFF);
            bits = (uint8_t)(bits << 1);
        }
    }

    lcd_set_window(x, y, FONT_W, FONT_H);
    lcd_wr_reg(CMD_RAMWR);
    dc_high();
    for (i = 0; i < (uint16_t)(FONT_W * FONT_H * 2); i++) {
        spi_tx(s_glyph[i]);
    }
    spi_flush();
}

void lcd_text(uint16_t x, uint16_t y, const char *s, uint16_t fg, uint16_t bg)
{
    while (*s) {
        if (x + FONT_W > LCD_W) break;
        lcd_char(x, y, *s, fg, bg);
        x = (uint16_t)(x + FONT_W);
        s++;
    }
}

void lcd_text_pad(uint16_t x, uint16_t y, const char *s, uint16_t fg, uint16_t bg,
                  uint16_t width_px)
{
    uint16_t cx = x;
    uint16_t end = (uint16_t)(x + width_px);

    while (*s && cx + FONT_W <= end) {
        lcd_char(cx, y, *s, fg, bg);
        cx = (uint16_t)(cx + FONT_W);
        s++;
    }
    /* 剩余部分填底色，抹掉上一屏的残影 */
    if (cx < end) {
        lcd_fill_rect(cx, y, (uint16_t)(end - cx), FONT_H, bg);
    }
}

void lcd_text_center(uint16_t y, const char *s, uint16_t fg, uint16_t bg)
{
    uint16_t len = 0;
    const char *p = s;
    while (*p) { len++; p++; }
    {
        uint16_t w = (uint16_t)(len * FONT_W);
        uint16_t x = (w < LCD_W) ? (uint16_t)((LCD_W - w) / 2) : 0;
        lcd_text(x, y, s, fg, bg);
    }
}

void lcd_text_u32(uint16_t x, uint16_t y, uint32_t v, uint16_t fg, uint16_t bg,
                  uint8_t pad_to)
{
    char buf[12];
    uint8_t n = 0, i;
    char out[12];

    if (v == 0) {
        buf[n++] = '0';
    } else {
        while (v && n < 10) {
            buf[n++] = (char)('0' + (v % 10U));
            v /= 10U;
        }
    }
    /* 反序 */
    for (i = 0; i < n; i++) {
        out[i] = buf[n - 1 - i];
    }
    /* 左补空格到 pad_to 位 */
    while (n < pad_to && n < 11) {
        for (i = n; i > 0; i--) {
            out[i] = out[i - 1];
        }
        out[0] = ' ';
        n++;
    }
    out[n] = '\0';
    lcd_text(x, y, out, fg, bg);
}
