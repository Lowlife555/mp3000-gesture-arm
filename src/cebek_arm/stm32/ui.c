/**
 * ui.c — 菜单状态机与屏幕绘制
 *
 * 按键约定（每个键都有短按和长按两种动作，一共 8 个功能，够用且不用翻菜单）：
 *
 *   ┌──────┬─────────────────┬──────────────────────────┐
 *   │      │ 短按            │ 长按（>500 ms）           │
 *   ├──────┼─────────────────┼──────────────────────────┤
 *   │ UP   │ 上一个关节      │ 时长 +1 档                │
 *   │ DOWN │ 下一个关节      │ 时长 -1 档                │
 *   │ OK   │ 按当前时长动一次│ **按住一直动，松开即停**  │
 *   │ BACK │ 切换方向 正/反  │ **急停**                  │
 *   └──────┴─────────────────┴──────────────────────────┘
 *
 * 三层独立的安全措施（任何一层都能让臂停下来）：
 *   1. STM32 自己：单次动作超过 3000 ms 强制停，按住模式也一样
 *   2. STM32 自己：串口链路丢心跳就立刻停，并且禁止再启动
 *   3. 树莓派：1500 ms 收不到新命令，看门狗自己发 00 00 00
 * 为什么需要三层：这台臂"发一条命令就一直动"，任何一处断了都必须有人踩刹车。
 */

#include "ui.h"
#include "lcd.h"
#include "keys.h"
#include "arm.h"
#include "delay.h"

#include <string.h>

/* 可选时长档位（毫秒） */
static const uint16_t s_dur_tab[] = { 50, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000 };
#define DUR_N   (sizeof(s_dur_tab) / sizeof(s_dur_tab[0]))
#define DUR_DEF 4U                                    /* 默认 300 ms */

#define LONG_MS         500U      /* 长按判定 */
#define OK_CONT_MS      300U      /* OK 进入"按住一直动"的门槛 */
#define BACK_ESTOP_MS   800U      /* BACK 急停门槛 */

/* ── 布局 ─────────────────────────────────────────────── */
#define ROW_H           20
#define JOINT_Y0        40
#define SEP_Y1          162
#define INFO_Y          166
#define STATUS_Y        222
#define HINT_Y          264

/* ── 状态 ─────────────────────────────────────────────── */
static uint8_t  s_sel;                 /* 0..ARMJ_COUNT-1 */
static uint8_t  s_dir;                 /* ARM_DIR_POS / ARM_DIR_NEG */
static uint8_t  s_dur_idx;

static uint8_t  s_moving;              /* 正在动作 */
static uint8_t  s_cont;                /* 按住一直动 */
static uint8_t  s_hold_capped;         /* 已经撞到 3 s 硬上限，必须松手 */
static uint32_t s_move_start;

static uint8_t  s_ok_cont_started;
static uint8_t  s_back_estop;
static uint8_t  s_up_long, s_down_long;

static uint32_t s_est_ms[ARMJ_COUNT];  /* 每个关节的累计通电时间（估算） */

static uint8_t  s_prev_link;
static char     s_status_buf[31];
static char     s_status2_buf[31];

/* ── 小工具 ───────────────────────────────────────────── */

static uint16_t cur_dur(void)
{
    return s_dur_tab[s_dur_idx];
}

static void put_u32_pad(char *dst, uint32_t v, uint8_t width)
{
    char tmp[11];
    uint8_t n = 0, i;
    if (v == 0) {
        tmp[n++] = '0';
    } else {
        while (v && n < 10) { tmp[n++] = (char)('0' + (v % 10U)); v /= 10U; }
    }
    while (n < width && n < 10) { tmp[n++] = ' '; }
    for (i = 0; i < n; i++) dst[i] = tmp[n - 1 - i];
    dst[n] = '\0';
}

/* "12.3" 形式的秒数 */
static void put_seconds(char *dst, uint32_t ms)
{
    uint32_t sec = ms / 1000U;
    uint32_t dec = (ms % 1000U) / 100U;
    char a[11];
    uint8_t i;
    put_u32_pad(a, sec, 1);
    i = 0;
    while (a[i] == ' ') i++;
    {
        uint8_t k = 0;
        while (a[i]) dst[k++] = a[i++];
        dst[k++] = '.';
        dst[k++] = (char)('0' + dec);
        dst[k] = '\0';
    }
}

/* ── 画各个区域 ───────────────────────────────────────── */

static void draw_header(void)
{
    lcd_fill_rect(0, 0, LCD_W, 18, COLOR_NAVY);
    lcd_text(4, 1, "CEBEK ARM  L476", COLOR_WHITE, COLOR_NAVY);
    lcd_fill_rect(0, 18, LCD_W, 2, COLOR_DGRAY);
}

static void draw_link(void)
{
    uint8_t ok = arm_link_ok();
    if (ok) {
        lcd_text(4, 22, "LINK OK            ", COLOR_GREEN, COLOR_BG);
    } else {
        lcd_text(4, 22, "LINK DOWN !        ", COLOR_RED, COLOR_BG);
    }
    s_prev_link = ok;
}

static void draw_joint_row(uint8_t i)
{
    uint8_t sel = (i == s_sel) ? 1U : 0U;
    uint16_t bg = sel ? COLOR_NAVY : COLOR_BG;
    uint16_t fg = sel ? COLOR_YELLOW : COLOR_LGRAY;
    uint16_t y = (uint16_t)(JOINT_Y0 + i * ROW_H);
    const char *n = arm_joint_name((arm_joint_t)i);
    const char *c = arm_joint_code((arm_joint_t)i);
    char buf[31];
    uint8_t k;

    lcd_fill_rect(0, y, LCD_W, ROW_H, bg);

    buf[0] = sel ? '>' : ' ';
    buf[1] = ' ';
    buf[2] = c[0];
    buf[3] = c[1];
    buf[4] = c[2];
    buf[5] = ' ';
    for (k = 0; k < 14 && n[k]; k++) {
        buf[6 + k] = n[k];
    }
    buf[6 + k] = '\0';

    lcd_text(4, (uint16_t)(y + 2), buf, fg, bg);

    /* 选中行右端显示该关节累计通电时间（估算值） */
    if (sel && i != ARMJ_LIGHT) {
        char txt[14];
        uint16_t w, x;
        put_seconds(txt, s_est_ms[i]);
        k = (uint8_t)strlen(txt);
        txt[k]     = 's';
        txt[k + 1] = '\0';
        w = (uint16_t)((k + 1) * FONT_W);
        x = (uint16_t)(LCD_W - 4 - w);
        lcd_text(x, (uint16_t)(y + 2), txt, COLOR_CYAN, bg);
    } else if (sel) {
        lcd_text((uint16_t)(LCD_W - 4 - 3 * FONT_W), (uint16_t)(y + 2),
                 "LED", COLOR_CYAN, bg);
    }
}

static void draw_joints_all(void)
{
    uint8_t i;
    for (i = 0; i < ARMJ_COUNT; i++) {
        draw_joint_row(i);
    }
}

static void draw_info(void)
{
    char buf[31];
    uint8_t k, n;

    /* DIR */
    {
        const char *d = (s_dir == ARM_DIR_POS) ? "POSITIVE" : "NEGATIVE";
        strcpy(buf, "DIR   ");
        for (k = 0; d[k]; k++) buf[6 + k] = d[k];
        buf[6 + k] = '\0';
        lcd_text_pad(4, INFO_Y, buf, COLOR_WHITE, COLOR_BG, LCD_W - 8);
    }

    /* TIME */
    {
        char num[12];
        strcpy(buf, "TIME  ");
        put_u32_pad(num, cur_dur(), 1);
        k = 0;
        while (num[k] == ' ') k++;
        n = 0;
        while (num[k]) buf[6 + n++] = num[k++];
        buf[6 + n++] = ' ';
        buf[6 + n++] = 'm';
        buf[6 + n++] = 's';
        buf[6 + n] = '\0';
        lcd_text_pad(4, (uint16_t)(INFO_Y + 16), buf, COLOR_WHITE, COLOR_BG, LCD_W - 8);
    }

    /* EST 总计（没有位置反馈，所以只能显示"命令累计"，不能显示角度） */
    {
        uint32_t tot = 0;
        char sec[12];
        for (k = 0; k < ARMJ_COUNT; k++) tot += s_est_ms[k];
        put_seconds(sec, tot);
        strcpy(buf, "EST   ");
        for (n = 0; sec[n]; n++) buf[6 + n] = sec[n];
        buf[6 + n]     = ' ';
        buf[6 + n + 1] = 's';
        buf[6 + n + 2] = '\0';
        lcd_text_pad(4, (uint16_t)(INFO_Y + 32), buf, COLOR_GRAY, COLOR_BG, LCD_W - 8);
    }
}

static void set_status(const char *s, const char *s2)
{
    strncpy(s_status_buf, s, 30);
    s_status_buf[30] = '\0';
    strncpy(s_status2_buf, s2 ? s2 : "", 30);
    s_status2_buf[30] = '\0';
}

static void draw_status(void)
{
    uint8_t moving = s_moving;
    uint16_t bg = moving ? COLOR_ORANGE : COLOR_TEAL;
    uint16_t fg = moving ? COLOR_BLACK : COLOR_WHITE;

    lcd_fill_rect(0, STATUS_Y, LCD_W, 18, bg);
    lcd_text_pad(4, (uint16_t)(STATUS_Y + 1), s_status_buf, fg, bg, LCD_W - 8);
    lcd_fill_rect(0, (uint16_t)(STATUS_Y + 18), LCD_W, 16, COLOR_BG);
    lcd_text_pad(4, (uint16_t)(STATUS_Y + 18), s_status2_buf, COLOR_GRAY, COLOR_BG, LCD_W - 8);
}

#define COLOR_HINT  0x7BEF      /* 暗一点的灰白，不抢主内容 */

static void draw_hints(void)
{
    lcd_text(4, (uint16_t)(HINT_Y),      "OK   tap = step",  COLOR_LGRAY, COLOR_BG);
    lcd_text(4, (uint16_t)(HINT_Y + 16), "OK   hold= run",   COLOR_HINT,  COLOR_BG);
    lcd_text(4, (uint16_t)(HINT_Y + 32), "BACK tap = dir",   COLOR_HINT,  COLOR_BG);
    lcd_text(4, (uint16_t)(HINT_Y + 48), "BACK hold= STOP",  COLOR_RED,   COLOR_BG);
}

/* ── 动作 ─────────────────────────────────────────────── */

static void stop_now(void)
{
    if (s_moving) {
        uint32_t dt = millis() - s_move_start;
        if (s_sel != ARMJ_LIGHT) {
            s_est_ms[s_sel] += dt;
        }
    }
    arm_stop();
    s_moving = 0;
    s_cont = 0;
}

static void start_motion(uint8_t continuous)
{
    if (!arm_link_ok()) {
        set_status("NO LINK - BLOCKED", "check UART / bridge");
        draw_status();
        return;
    }
    if (s_sel == ARMJ_LIGHT) {
        /* 灯不需要计时，按一下就把当前状态发过去（由 s_dir 决定开/关） */
        arm_command(ARMJ_LIGHT, s_dir);
        set_status(s_dir == ARM_DIR_POS ? "LIGHT ON" : "LIGHT OFF", "tap OK to toggle");
        draw_status();
        return;
    }
    arm_command((arm_joint_t)s_sel, s_dir);
    s_move_start = millis();
    s_moving = 1;
    s_cont = continuous;
    s_hold_capped = 0;

    {
        char l1[31], l2[31];
        strcpy(l1, "RUN  ");
        strcat(l1, arm_joint_code((arm_joint_t)s_sel));
        strcat(l1, " ");
        strcat(l1, (s_dir == ARM_DIR_POS) ? "+" : "-");
        strcat(l1, continuous ? "  HOLD" : "  STEP");
        strcpy(l2, arm_joint_name((arm_joint_t)s_sel));
        strcat(l2, "  0 ms");
        set_status(l1, l2);
    }
    draw_status();
}

/* ── 按键处理 ─────────────────────────────────────────── */

static void handle_keys(void)
{
    uint8_t pr = keys_take_pressed();
    uint8_t rl = keys_take_released();
    uint32_t now = millis();

    /* ---- UP / DOWN：短按选关节，长按调时长 ---- */
    if (pr & KEY_BIT(KEY_UP))   { s_up_long = 0; }
    if (pr & KEY_BIT(KEY_DOWN)) { s_down_long = 0; }

    if (!s_up_long && (keys_down() & KEY_BIT(KEY_UP)) && keys_held_ms(KEY_UP) >= LONG_MS) {
        s_up_long = 1;
        if (s_dur_idx + 1U < DUR_N) s_dur_idx++;
        draw_info();
    }
    if (!s_down_long && (keys_down() & KEY_BIT(KEY_DOWN)) && keys_held_ms(KEY_DOWN) >= LONG_MS) {
        s_down_long = 1;
        if (s_dur_idx > 0) s_dur_idx--;
        draw_info();
    }

    if (rl & KEY_BIT(KEY_UP)) {
        if (!s_up_long) {
            uint8_t prev = s_sel;
            s_sel = (uint8_t)((s_sel + ARMJ_COUNT - 1U) % ARMJ_COUNT);
            draw_joint_row(prev);
            draw_joint_row(s_sel);
        }
        s_up_long = 0;
    }
    if (rl & KEY_BIT(KEY_DOWN)) {
        if (!s_down_long) {
            uint8_t prev = s_sel;
            s_sel = (uint8_t)((s_sel + 1U) % ARMJ_COUNT);
            draw_joint_row(prev);
            draw_joint_row(s_sel);
        }
        s_down_long = 0;
    }

    /* ---- OK：长按一直动，短按走一步 ---- */
    if ((pr & KEY_BIT(KEY_OK))) {
        s_ok_cont_started = 0;
    }
    if (!s_ok_cont_started && (keys_down() & KEY_BIT(KEY_OK))
        && keys_held_ms(KEY_OK) >= OK_CONT_MS && !s_hold_capped) {
        s_ok_cont_started = 1;
        start_motion(1);
    }
    if (rl & KEY_BIT(KEY_OK)) {
        if (s_ok_cont_started) {
            stop_now();
            s_hold_capped = 0;
            set_status("STOPPED", "release-to-stop");
            draw_status();
            draw_joint_row(s_sel);
            draw_info();
        } else {
            start_motion(0);
        }
        s_ok_cont_started = 0;
    }

    /* ---- BACK：长按急停，短按切方向 ---- */
    if (!s_back_estop && (keys_down() & KEY_BIT(KEY_BACK))
        && keys_held_ms(KEY_BACK) >= BACK_ESTOP_MS) {
        s_back_estop = 1;
        stop_now();
        s_hold_capped = 0;
        set_status("E-STOP SENT", "00 00 00");
        draw_status();
        draw_joint_row(s_sel);
        draw_info();
    }
    if (rl & KEY_BIT(KEY_BACK)) {
        if (!s_back_estop) {
            s_dir = (s_dir == ARM_DIR_POS) ? ARM_DIR_NEG : ARM_DIR_POS;
            draw_info();
        }
        s_back_estop = 0;
    }

    (void)now;
}

/* ── 超时与安全 ───────────────────────────────────────── */

static void handle_timing(void)
{
    uint32_t now = millis();

    /* 链路一断，立刻停 —— 这是第二层保险 */
    if (s_moving && !arm_link_ok()) {
        stop_now();
        set_status("LINK LOST - STOP", "motors off");
        draw_status();
        draw_joint_row(s_sel);
        draw_info();
    }

    if (!s_moving) {
        return;
    }

    if (s_cont) {
        /* 按住模式也受 3 s 硬上限约束 */
        if ((now - s_move_start) >= ARM_MAX_MS) {
            stop_now();
            s_hold_capped = 1;      /* 必须松手才能再启动 */
            set_status("3s CAP HIT - STOP", "release OK first");
            draw_status();
            draw_joint_row(s_sel);
            draw_info();
        } else {
            char l2[31];
            strcpy(l2, arm_joint_name((arm_joint_t)s_sel));
            strcat(l2, " ");
            put_u32_pad(l2 + strlen(l2), (now - s_move_start), 1);
            strcat(l2, " ms");
            strncpy(s_status2_buf, l2, 30);
            s_status2_buf[30] = '\0';
            lcd_text_pad(4, (uint16_t)(STATUS_Y + 18), s_status2_buf, COLOR_GRAY, COLOR_BG, LCD_W - 8);
        }
    } else {
        if ((now - s_move_start) >= cur_dur()) {
            stop_now();
            set_status("READY", "step done");
            draw_status();
            draw_joint_row(s_sel);
            draw_info();
        }
    }
}

/* ── 对外 ─────────────────────────────────────────────── */

void ui_init(void)
{
    s_sel = ARMJ_SHOULDER;      /* 上电停在"肩部"，最常用的关节 */
    s_dir = ARM_DIR_POS;
    s_dur_idx = DUR_DEF;
    s_moving = 0;
    s_cont = 0;
    s_hold_capped = 0;
    s_ok_cont_started = 0;
    s_back_estop = 0;
    s_up_long = s_down_long = 0;
    s_prev_link = 0xFF;

    {
        uint8_t i;
        for (i = 0; i < ARMJ_COUNT; i++) s_est_ms[i] = 0;
    }

    draw_header();
    draw_link();
    draw_joints_all();
    lcd_fill_rect(0, SEP_Y1, LCD_W, 2, COLOR_DGRAY);
    lcd_fill_rect(0, (uint16_t)(STATUS_Y - 6), LCD_W, 2, COLOR_DGRAY);
    draw_info();
    set_status("READY", "waiting for link");
    draw_status();
    draw_hints();
}

void ui_task(void)
{
    handle_keys();
    handle_timing();

    if (arm_link_ok() != s_prev_link) {
        draw_link();
    }
}
