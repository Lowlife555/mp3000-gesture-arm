/**
 * lcd.h — ILI9341 240x320 RGB565，硬件 SPI1，寄存器级驱动
 *
 * 设计取舍：**不开帧缓冲**。
 *   240 * 320 * 2 = 150 KB，而 L476RG 只有 96 KB SRAM —— 放不下。
 *   所以每次只画"需要变的那一小块"（局部窗口），
 *   既省内存又省 SPI 流量，屏上也不会闪。
 *
 * SPI 速率 80 MHz / 8 = 10 MHz（ILI9341 写周期下限 66 ns，即最高约 15 MHz，
 *   10 MHz 留了余量）。一个 8x16 字符 = 256 字节 ≈ 205 us。
 */

#ifndef LCD_ILI9341_H
#define LCD_ILI9341_H

#include <stdint.h>

#define LCD_W       240
#define LCD_H       320

/* 常用颜色（RGB565） */
#define COLOR_BLACK     0x0000
#define COLOR_WHITE     0xFFFF
#define COLOR_RED       0xF800
#define COLOR_GREEN     0x07E0
#define COLOR_BLUE      0x001F
#define COLOR_YELLOW    0xFFE0
#define COLOR_CYAN      0x07FF
#define COLOR_MAGENTA   0xF81F
#define COLOR_GRAY      0x8410
#define COLOR_DGRAY     0x4208
#define COLOR_LGRAY     0xC618
#define COLOR_ORANGE    0xFD20
#define COLOR_NAVY      0x000F
#define COLOR_TEAL      0x0410
#define COLOR_BG        0x0000     /* 深底 */

#define FONT_H          16
#define FONT_W          8

void lcd_init(void);
void lcd_set_backlight(int on);         /* 本板无背光脚，保留接口空实现 */

void lcd_fill_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);
void lcd_clear(uint16_t color);
void lcd_hline(uint16_t x, uint16_t y, uint16_t w, uint16_t color);
void lcd_vline(uint16_t x, uint16_t y, uint16_t h, uint16_t color);
void lcd_frame(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);

/* 8x16 ASCII，不透明（自带底色），比逐点写快一个数量级 */
void lcd_char(uint16_t x, uint16_t y, char ch, uint16_t fg, uint16_t bg);
void lcd_text(uint16_t x, uint16_t y, const char *s, uint16_t fg, uint16_t bg);
/* 在给定宽度内填空格到行尾，用于抹掉上一行的残影 */
void lcd_text_pad(uint16_t x, uint16_t y, const char *s, uint16_t fg, uint16_t bg,
                  uint16_t width_px);
void lcd_text_center(uint16_t y, const char *s, uint16_t fg, uint16_t bg);
/* 数值格式化后显示（不依赖 printf 减小代码体积） */
void lcd_text_u32(uint16_t x, uint16_t y, uint32_t v, uint16_t fg, uint16_t bg,
                  uint8_t pad_to);

#endif /* LCD_ILI9341_H */
