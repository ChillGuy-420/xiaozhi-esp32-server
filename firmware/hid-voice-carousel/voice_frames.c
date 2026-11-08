#include "voice_frames.h"

#include "voice_carousel.h"

#include "lvgl.h"

extern const uint8_t voice_mode_rgb565_start[] asm("_binary_voice_mode_rgb565_start");
extern const uint8_t voice_mode_rgb565_end[] asm("_binary_voice_mode_rgb565_end");
extern const uint8_t voice_mode_2_rgb565_start[] asm("_binary_voice_mode_2_rgb565_start");
extern const uint8_t voice_mode_2_rgb565_end[] asm("_binary_voice_mode_2_rgb565_end");
extern const uint8_t voice_mode_3_rgb565_start[] asm("_binary_voice_mode_3_rgb565_start");
extern const uint8_t voice_mode_3_rgb565_end[] asm("_binary_voice_mode_3_rgb565_end");
extern const uint8_t voice_mode_4_rgb565_start[] asm("_binary_voice_mode_4_rgb565_start");
extern const uint8_t voice_mode_4_rgb565_end[] asm("_binary_voice_mode_4_rgb565_end");
extern const uint8_t voice_mode_5_rgb565_start[] asm("_binary_voice_mode_5_rgb565_start");
extern const uint8_t voice_mode_5_rgb565_end[] asm("_binary_voice_mode_5_rgb565_end");

static const uint8_t *const s_data[VOICE_FRAME_COUNT] = {
    voice_mode_rgb565_start,
    voice_mode_2_rgb565_start,
    voice_mode_3_rgb565_start,
    voice_mode_4_rgb565_start,
    voice_mode_5_rgb565_start,
};
static const uint8_t *const s_end[VOICE_FRAME_COUNT] = {
    voice_mode_rgb565_end,
    voice_mode_2_rgb565_end,
    voice_mode_3_rgb565_end,
    voice_mode_4_rgb565_end,
    voice_mode_5_rgb565_end,
};

static lv_draw_buf_t s_buf[VOICE_FRAME_COUNT];
static lv_obj_t *s_img;
static voice_carousel_t s_carousel;
static int s_shown = -1;
static bool s_visible;

static void tick_cb(lv_timer_t *timer) {
    (void)timer;
    int frame = voice_carousel_tick(&s_carousel, s_visible ? UI_MODE_VOICE : UI_MODE_DESK, s_visible,
                                    lv_tick_get());
    if (frame < 0 || frame == s_shown || s_img == NULL) {
        return;
    }
    s_shown = frame;
    lv_image_set_src(s_img, &s_buf[frame]);
}

void voice_frames_attach(lv_obj_t *voice_screen) {
    for (int i = 0; i < VOICE_FRAME_COUNT; ++i) {
        size_t len = (size_t)(s_end[i] - s_data[i]);
        if (len != VOICE_FRAME_BYTES) {
            return;
        }
        if (lv_draw_buf_init(&s_buf[i], VOICE_FRAME_W, VOICE_FRAME_H, LV_COLOR_FORMAT_RGB565,
                             VOICE_FRAME_W * 2, (void *)s_data[i], len) != LV_RESULT_OK) {
            return;
        }
    }
    voice_carousel_init(&s_carousel);
    voice_carousel_mark_decoded(&s_carousel);
    s_img = lv_image_create(voice_screen);
    lv_obj_set_clickable(s_img, false);
    lv_obj_set_pos(s_img, 0, 0);
    lv_image_set_src(s_img, &s_buf[0]);
    lv_obj_move_background(s_img);
    s_shown = 0;
    s_visible = true;
    lv_timer_create(tick_cb, 1000, NULL);
}

void voice_frames_set_shown(bool voice_screen_visible) {
    s_visible = voice_screen_visible;
}
