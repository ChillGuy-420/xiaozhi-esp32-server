#ifndef VOICE_CAROUSEL_H
#define VOICE_CAROUSEL_H

#include <stddef.h>
#include <stdint.h>

#define VOICE_FRAME_COUNT 5
#define VOICE_FRAME_W 480
#define VOICE_FRAME_H 480
#define VOICE_FRAME_BYTES (VOICE_FRAME_W * VOICE_FRAME_H * 2)
#define VOICE_CAROUSEL_MS 8000u

typedef enum {
    UI_MODE_VOICE = 0,
    UI_MODE_DESK = 1,
} ui_mode_t;

typedef struct {
    int index;
    uint32_t shown_since_ms;
    int decoded_once;
    int dwell_pending;
} voice_carousel_t;

void voice_carousel_init(voice_carousel_t *carousel);
void voice_carousel_mark_decoded(voice_carousel_t *carousel);
int voice_carousel_frame(const voice_carousel_t *carousel, ui_mode_t mode, int voice_screen_visible);
int voice_carousel_tick(voice_carousel_t *carousel, ui_mode_t mode, int voice_screen_visible, uint32_t now_ms);

#endif
