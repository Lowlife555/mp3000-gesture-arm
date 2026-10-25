/**
 * ui.h — 界面与交互状态机
 */
#ifndef UI_H
#define UI_H

void ui_init(void);

/* 主循环里每轮调用：处理按键、超时、链路变化，并按需重绘 */
void ui_task(void);

#endif /* UI_H */
