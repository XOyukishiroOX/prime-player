"""Small complete English and Simplified Chinese UI catalog."""

CATALOG = {
    "ZH_CN": {
        "files": "%d 个视频", "no_files": "未找到 .M1V 或 .MJPG 视频",
        "play": "播放", "exit": "退出", "settings": "设置",
        "settings_title": "播放器设置", "save": "保存", "cancel": "取消",
        "language": "语言", "theme": "主题", "scale": "画面缩放",
        "overlay": "信息叠层", "end_mode": "播完行为",
        "timing": "高帧率策略", "playback_error": "播放错误",
        "return_list": "返回列表", "pause": "暂停", "playing": "播放中",
        "seeking": "定位", "memory_error": "可用内存不足，无法播放此分辨率",
        "settings_error": "设置文件损坏", "reset_settings": "ENTER 重置 / ESC 退出",
        "list_help": "ENTER 播放   ESC 退出   HELP 设置",
        "settings_help": "左右修改   ENTER 保存   ESC 取消",
        "seek_help": "定位 %d.%d%%  上下:0.1 左右:5 ENTER:确定",
        "play_help": "%s %s  ENTER:%s ESC:列表 HELP:叠层",
        "detail_time": "%s 帧:%s 时间:%dms",
        "detail_stats": "读:%d/%dK 位置:%d.%d%% 迟:%d 显:%d 跳:%d",
        "ZH_CN": "简体中文", "EN": "English", "DARK": "深色",
        "LIGHT": "浅色", "FIT": "适应", "ORIGINAL": "原始",
        "FILL": "填充", "STRETCH": "拉伸", "OFF": "关闭",
        "PROGRESS": "进度", "FULL": "详细", "ONCE": "单次返回",
        "SINGLE": "单曲循环", "ALL": "列表循环", "SYNC": "同步优先",
        "COMPLETE": "完整帧优先",
    },
    "EN": {
        "files": "%d video(s)", "no_files": "No .M1V or .MJPG videos",
        "play": "Play", "exit": "Exit", "settings": "Settings",
        "settings_title": "Player settings", "save": "Save", "cancel": "Cancel",
        "language": "Language", "theme": "Theme", "scale": "Scaling",
        "overlay": "Information", "end_mode": "At end",
        "timing": "High-FPS mode", "playback_error": "Playback error",
        "return_list": "Return to list", "pause": "Pause", "playing": "Playing",
        "seeking": "Seek", "memory_error": "Not enough memory for this resolution",
        "settings_error": "Settings file is damaged",
        "reset_settings": "ENTER reset / ESC exit", "ZH_CN": "简体中文",
        "list_help": "ENTER play   ESC exit   HELP settings",
        "settings_help": "LEFT/RIGHT change   ENTER save   ESC cancel",
        "seek_help": "Seek %d.%d%% U/D:0.1 L/R:5 ENTER:apply",
        "play_help": "%s %s  ENTER:%s ESC:list HELP:overlay",
        "detail_time": "%s f:%s t:%dms",
        "detail_stats": "r:%d/%dK pos:%d.%d%% late:%d p:%d d:%d",
        "EN": "English", "DARK": "Dark", "LIGHT": "Light", "FIT": "Fit",
        "ORIGINAL": "Original", "FILL": "Fill", "STRETCH": "Stretch",
        "OFF": "Off", "PROGRESS": "Progress", "FULL": "Details",
        "ONCE": "Return", "SINGLE": "Repeat one", "ALL": "Repeat all",
        "SYNC": "Sync first", "COMPLETE": "Every frame",
    },
}


def text(language, key, *values):
    catalog = CATALOG.get(language, CATALOG["ZH_CN"])
    value = catalog.get(key, key)
    return value % values if values else value
