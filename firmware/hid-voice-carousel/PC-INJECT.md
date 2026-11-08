# 語音輪播與桌面圖：電腦上才能完成的注入

雲端沒有 `wallpaper.rgb565`，也沒有 `app_face.c` / `app_face.h`。桌面照片沒有被替換，也沒有在雲端建置進韌體。下面是在原本那份 `~/esp32s3-hid` 上套用的最小步驟。不要跑 `tools/make_wallpaper.py`：來源 jpg 不在雲端，那個腳本在缺檔時會寫出一張漸層替代圖。

## 先核對既有桌面圖，不要重做

在韌體根目錄：

```bash
test "$(wc -c < main/assets/wallpaper.rgb565)" -eq 460800
sha256sum main/assets/wallpaper.rgb565
```

預期 SHA256 是 sanitize 清單裡的原檔：

`eca6cf65d340f5df09dc0891ba40477a4cc9f1175a5114731523a2e14314fe09`

不一致就停。不要用別的圖補上。

## 語音五張，獨立檔名

五張 RGB565 是 480x480、小端、各 460800 位元組，等比例留黑邊，不裁切。檔名是 `voice-mode.rgb565` 到 `voice-mode-5.rgb565`，不是 `wallpaper.rgb565`。把這五個檔放到 `main/assets/voice/`。CMake 在既有那一行之外追加，不要拿掉桌面圖：

```
EMBED_FILES "assets/wallpaper.rgb565"
            "assets/voice/voice-mode.rgb565"
            "assets/voice/voice-mode-2.rgb565"
            "assets/voice/voice-mode-3.rgb565"
            "assets/voice/voice-mode-4.rgb565"
            "assets/voice/voice-mode-5.rgb565"
```

`voice_carousel.c` 只在語音畫面顯示時每 8 秒換一張，桌面模式不推進、不畫這五張。通知與天氣網址沒有接進來。

## 還不能改語音畫面的原因

語音畫面唯一的建立點是 `app_ui.c` 的 `s_face = face_create(scr)`。`face_create`、`face_run`、`FACE_W`、`FACE_H` 都在尚未提供的：

- `main/app_face.h`
- `main/app_face.c`

沒有這兩個檔，就不能把輪播接到現有表情物件，也不能聲稱桌面行為已經在裝置上保留。桌面載圖仍只在 `app_desk.c` 的 `load_wallpaper()`，符號是 `_binary_wallpaper_rgb565_start`。
