# 單一路徑：沿用既有 HID 韌體

小智整包映像和 `~/esp32s3-hid` 不是同一個程式。小智映像沒有桌面／語音滑動切換，也沒有 `wallpaper.rgb565`。燒進小智會拿掉現在的桌面。裝置端只改既有這份 HID 韌體；後端仍是已做好的隔離伺服器（裝置憑據、拒絕 `tenclass.net`、空權杖與缺少私人 CA 都不連線）。

`voice-carousel.patch` 只改 `main/app_ui.c` 與 `main/CMakeLists.txt`，並新增輪播檔。`app_desk.c` 的 `load_wallpaper()` 與 `app_face.c` / `app_face.h` 都不改。桌面繼續嵌 `assets/wallpaper.rgb565`。五張圖只出現在語音畫面，表情物件隱藏，30fps 表情計時停掉，避免蓋住圖或佔著繪圖。換圖只換指標，不重解碼。

在 HID 根目錄、確認工作樹乾淨後：

```bash
test "$(wc -c < main/assets/wallpaper.rgb565)" -eq 460800
sha256sum main/assets/wallpaper.rgb565
mkdir -p main/assets/voice
# 放入五個 460800 位元組的 voice-mode.rgb565 … voice-mode-5.rgb565
patch -p1 < voice-carousel.patch
```

壁紙 SHA256 必須是 `eca6cf65d340f5df09dc0891ba40477a4cc9f1175a5114731523a2e14314fe09`。不要跑 `tools/make_wallpaper.py`。

伺服器端的憑據與 CA 檢查已經在隔離後端。HID 裡真正開連線的是 `main/app_net.c`，這次來源沒有它，所以這份 patch 還沒有把 `Device-Credential` 送進裝置。那是同一條路徑的下一小段，不是另一份韌體。

本機 `build/bootloader/bootloader.bin` 是 22496 位元組，SHA256 `970321be98c50a8f8398ec181dc769dce97e86ce29c98308cd7f84c0c3ac39ac`。雲端小智建置的 bootloader 是 16528 位元組、另一個雜湊。兩者都還沒有和板上的啟動程式比對，不能當成相容。
