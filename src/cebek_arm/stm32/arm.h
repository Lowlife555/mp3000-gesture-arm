/**
 * arm.h — 机械臂指令层（把"关节+方向"翻译成 USB 那 3 个字节，经串口交给树莓派）
 *
 * 协议（原厂 OWI-535，已在本机实测确认）：
 *   byte0 [1:0]=夹爪 [3:2]=腕 [5:4]=肘 [7:6]=肩，每段 00=停 / 01=正 / 10=反
 *   byte1 [1:0]=底座 00=停 / 01=CW / 10=CCW
 *   byte2 bit0 = 爪内灯（Search Light）
 *   语义：**发一条就一直动，直到下一条命令**。停止就是发 00 00 00。
 *
 * 这一层只负责"造句"，不负责计时 —— 计时在 ui.c，因为硬上限 3 s
 * 是和用户交互绑在一起的，放在指令层反而看不清。
 */

#ifndef ARM_H
#define ARM_H

#include <stdint.h>

typedef enum {
    ARMJ_GRIPPER = 0,
    ARMJ_WRIST,
    ARMJ_ELBOW,
    ARMJ_SHOULDER,
    ARMJ_BASE,
    ARMJ_LIGHT,
    ARMJ_COUNT
} arm_joint_t;

#define ARM_DIR_STOP    0U
#define ARM_DIR_POS     1U
#define ARM_DIR_NEG     2U

/* 单次动作硬上限（毫秒）。超过就强制停，和树莓派侧看门狗是两道独立保险。 */
#define ARM_MAX_MS      3000U

void arm_init(void);

/* 主循环里每轮调用：收串口回话、更新链路状态 */
void arm_poll(void);

/* 发原始三字节（调试用） */
void arm_send_raw(uint8_t b0, uint8_t b1, uint8_t b2);

/* 让某个关节按 dir 动，其余关节全停。light 只对 ARMJ_LIGHT 有意义。 */
void arm_command(arm_joint_t j, uint8_t dir);

/* 全停（00 00 00） */
void arm_stop(void);

/* 心跳 */
void arm_ping(void);

/* 链路是否可用：最近 1500 ms 内收到过 PONG */
uint8_t arm_link_ok(void);

/* 诊断计数 */
uint32_t arm_ok_count(void);
uint32_t arm_err_count(void);
uint32_t arm_tmo_count(void);
const char *arm_last_reply(void);

/* 名字（屏上只有 ASCII 字模，所以用英文） */
const char *arm_joint_name(arm_joint_t j);
const char *arm_joint_code(arm_joint_t j);

#endif /* ARM_H */
