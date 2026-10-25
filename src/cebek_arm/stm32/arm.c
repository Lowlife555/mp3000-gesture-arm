/**
 * arm.c — 指令编码 + 与树莓派的文本行协议
 *
 * 线协议（和树莓派上的 cebek_bridge.py 一一对应）：
 *   发： ARM <b0> <b1> <b2>\n     PING\n    STOP\n
 *   收： OK / PONG / ERR <原因> / TMO
 *
 * 为什么不用二进制帧：
 *   用的是 ST-LINK 虚拟串口，随时可能热插拔。ASCII 文本行的好处是
 *   一插上就能重新对齐，不会因为丢了半个帧就永久错位。
 */

#include "arm.h"
#include "uart2.h"
#include "delay.h"

#include <string.h>

#define LINK_TIMEOUT_MS     1500U

static volatile uint32_t s_last_pong_ms;
static volatile uint8_t  s_got_pong_once;
static volatile uint32_t s_ok_cnt, s_err_cnt, s_tmo_cnt;
static char              s_last_reply[20];

/* ── 编码 ─────────────────────────────────────────────── */

void arm_send_raw(uint8_t b0, uint8_t b1, uint8_t b2)
{
    static const char hex[] = "0123456789ABCDEF";
    char buf[20];

    buf[0]  = 'A'; buf[1] = 'R'; buf[2] = 'M'; buf[3] = ' ';
    buf[4]  = hex[(b0 >> 4) & 0x0F];
    buf[5]  = hex[b0 & 0x0F];
    buf[6]  = ' ';
    buf[7]  = hex[(b1 >> 4) & 0x0F];
    buf[8]  = hex[b1 & 0x0F];
    buf[9]  = ' ';
    buf[10] = hex[(b2 >> 4) & 0x0F];
    buf[11] = hex[b2 & 0x0F];
    buf[12] = '\n';
    buf[13] = '\0';

    uart2_puts(buf);
    uart2_flush();
}

void arm_command(arm_joint_t j, uint8_t dir)
{
    uint8_t b0 = 0, b1 = 0, b2 = 0;

    if (dir == ARM_DIR_STOP) {
        arm_send_raw(0, 0, 0);
        return;
    }

    switch (j) {
    case ARMJ_GRIPPER:  b0 |= (uint8_t)(dir << 0);  break;
    case ARMJ_WRIST:    b0 |= (uint8_t)(dir << 2);  break;
    case ARMJ_ELBOW:    b0 |= (uint8_t)(dir << 4);  break;
    case ARMJ_SHOULDER: b0 |= (uint8_t)(dir << 6);  break;
    case ARMJ_BASE:     b1 |= (uint8_t)(dir << 0);  break;
    case ARMJ_LIGHT:
        b2 = (dir == ARM_DIR_POS) ? 1U : 0U;        /* 灯只有开/关 */
        break;
    default:
        break;
    }
    arm_send_raw(b0, b1, b2);
}

void arm_stop(void)
{
    arm_send_raw(0, 0, 0);
}

void arm_ping(void)
{
    uart2_puts("PING\n");
    uart2_flush();
}

/* ── 回话解析 ─────────────────────────────────────────── */

void arm_poll(void)
{
    char line[32];

    /* 一次最多处理 4 行，避免回话很多时把主循环卡住 */
    {
        uint8_t n;
        for (n = 0; n < 4; n++) {
            if (!uart2_getline(line, sizeof(line))) {
                break;
            }
            /* 记录最近一条，供屏上显示 */
            {
                uint8_t i;
                for (i = 0; i < sizeof(s_last_reply) - 1U && line[i]; i++) {
                    s_last_reply[i] = line[i];
                }
                s_last_reply[i] = '\0';
            }

            if (strcmp(line, "OK") == 0) {
                s_ok_cnt++;
            } else if (strcmp(line, "PONG") == 0) {
                s_last_pong_ms = millis();
                s_got_pong_once = 1;
            } else if (strcmp(line, "TMO") == 0) {
                s_tmo_cnt++;          /* 树莓派看门狗踩了刹车 */
            } else if (strncmp(line, "ERR", 3) == 0) {
                s_err_cnt++;
            }
            /* 其它行忽略 */
        }
    }
}

uint8_t arm_link_ok(void)
{
    if (!s_got_pong_once) {
        return 0;
    }
    return ((uint32_t)(millis() - s_last_pong_ms) < LINK_TIMEOUT_MS) ? 1U : 0U;
}

uint32_t arm_ok_count(void)   { return s_ok_cnt; }
uint32_t arm_err_count(void)  { return s_err_cnt; }
uint32_t arm_tmo_count(void)  { return s_tmo_cnt; }
const char *arm_last_reply(void) { return s_last_reply; }

void arm_init(void)
{
    uart2_init(115200);
    delay_ms(50);

    s_last_pong_ms = 0;
    s_got_pong_once = 0;
    s_ok_cnt = s_err_cnt = s_tmo_cnt = 0;
    s_last_reply[0] = '\0';

    /* 上电第一件事：把机械臂停住。如果之前它正被别的程序驱动着，
     * 这一条能防止它一上电就乱动。 */
    arm_stop();
    delay_ms(20);
    arm_ping();
}

const char *arm_joint_name(arm_joint_t j)
{
    switch (j) {
    case ARMJ_GRIPPER:  return "GRIPPER";
    case ARMJ_WRIST:    return "WRIST";
    case ARMJ_ELBOW:    return "ELBOW";
    case ARMJ_SHOULDER: return "SHOULDER";
    case ARMJ_BASE:     return "BASE";
    case ARMJ_LIGHT:    return "LIGHT";
    default:            return "?";
    }
}

const char *arm_joint_code(arm_joint_t j)
{
    switch (j) {
    case ARMJ_GRIPPER:  return "M1";
    case ARMJ_WRIST:    return "M2";
    case ARMJ_ELBOW:    return "M3";
    case ARMJ_SHOULDER: return "M4";
    case ARMJ_BASE:     return "M5";
    case ARMJ_LIGHT:    return "LED";
    default:            return "--";
    }
}
